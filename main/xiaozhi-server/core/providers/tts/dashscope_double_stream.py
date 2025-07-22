# coding=utf-8
import os
import queue
import asyncio
import traceback
import threading
import time
from datetime import datetime
from config.logger import setup_logging
from core.utils.tts import MarkdownCleaner
from core.providers.tts.base import TTSProviderBase
from core.utils import opus_encoder_utils
from core.utils.util import check_model_key
from core.providers.tts.dto.dto import SentenceType, ContentType, InterfaceType
from core.handle.sendAudioHandle import sendAudioMessage
from core.utils.output_counter import add_device_output
from core.handle.reportHandle import enqueue_tts_report

try:
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat, ResultCallback
except ImportError:
    dashscope = None
    SpeechSynthesizer = None
    AudioFormat = None
    ResultCallback = None

TAG = __name__
logger = setup_logging()


class DashScopeCallback(ResultCallback):
    """阿里云DashScope TTS回调处理类"""
    
    def __init__(self, tts_provider):
        self.tts_provider = tts_provider
        self.is_first_data = True
        self.should_finish_session = False  # 标志是否需要在完成时结束会话
        self.opus_datas_cache = []  # Opus数据缓存
        self.first_sentence_segment_count = 0  # 第一句话的段数计数
        self.is_first_sentence = True  # 是否是第一句话
        self.cache_timer = None  # 缓存定时器
        self.cache_send_interval = 0.06  # 60ms发送间隔
        
    def on_open(self):
        logger.bind(tag=TAG).info("DashScope TTS连接建立")
        
    def on_complete(self):
        logger.bind(tag=TAG).info("DashScope TTS语音合成完成")
        
        # 检查客户端是否中止
        if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
            logger.bind(tag=TAG).info("收到打断信息，跳过合成完成处理")
            return
        
        # 停止定时器并发送缓存的音频数据
        self._stop_cache_timer()
        self._flush_cached_audio(is_final=True)
        
        # 处理会话结束前的音频文件
        if hasattr(self.tts_provider, '_process_before_stop_play_files'):
            self.tts_provider._process_before_stop_play_files()
        
        # 如果需要结束会话，在合成完成后结束TTS会话
        if self.should_finish_session:
            try:
                logger.bind(tag=TAG).info("TTS合成完成，开始结束TTS会话...")
                # 异步调用资源清理
                future = asyncio.run_coroutine_threadsafe(
                    self.tts_provider.close(),
                    loop=self.tts_provider.conn.loop,
                )
                future.result()
                self.should_finish_session = False  # 重置标志
                logger.bind(tag=TAG).info("TTS会话已完全结束")
            except Exception as e:
                logger.bind(tag=TAG).error(f"结束TTS会话失败: {str(e)}")
            
    def on_error(self, message: str):
        logger.bind(tag=TAG).error(f"DashScope TTS语音合成出现异常：{message}")
        # 发生错误时也检查是否需要清理
        if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
            logger.bind(tag=TAG).info("错误发生时收到打断信息，跳过错误处理")
            return
        
    def on_close(self):
        logger.bind(tag=TAG).info("DashScope TTS连接关闭")
        # 停止定时器
        self._stop_cache_timer()
        # 连接关闭时检查是否是因为打断
        if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
            logger.bind(tag=TAG).info("因打断而关闭连接")
        
    def on_event(self, message):
        logger.bind(tag=TAG).debug(f"DashScope TTS事件: {message}")
        # 事件处理时也检查打断状态
        if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
            logger.bind(tag=TAG).info("收到打断信息，跳过事件处理")
            return
        
    def on_data(self, data: bytes) -> None:
        """接收音频数据回调"""
        logger.bind(tag=TAG).debug(f"接收到音频数据，长度：{len(data)}")
        
        # 检查客户端是否中止
        if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
            logger.bind(tag=TAG).info("收到打断信息，终止音频数据处理")
            return
        
        # 参考豆包双流式逻辑：PCM数据接收后立即编码为Opus，不进行缓存
        self._process_audio_data(data, is_first=self.is_first_data)
        
        # 标记首次数据已处理
        if self.is_first_data:
            self.is_first_data = False
            
    def _process_audio_data(self, audio_data, is_first=False, is_last=False):
        """处理音频数据并转换为Opus格式，实现智能缓存机制"""
        try:
            # 检查客户端是否中止
            if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
                logger.bind(tag=TAG).info("收到打断信息，跳过音频数据处理")
                return
            
            # 将PCM数据转换为Opus格式
            opus_datas = self.tts_provider.pcm_to_opus_data(audio_data, is_end=is_last)
            
            # 智能缓存策略：参考豆包双流式逻辑
            if self.is_first_sentence:
                # 第一句话：前6个段立即播放，后续段缓存
                if self.first_sentence_segment_count < 6:
                    # 立即发送前6个段
                    sentence_type = SentenceType.FIRST if is_first else SentenceType.MIDDLE
                    self.tts_provider.tts_audio_queue.put(
                        (sentence_type, opus_datas, None)
                    )
                    logger.bind(tag=TAG).debug(f"第一句话第{self.first_sentence_segment_count + 1}段立即发送")
                else:
                    # 后续段缓存
                    self.opus_datas_cache.extend(opus_datas)
                    logger.bind(tag=TAG).debug(f"第一句话第{self.first_sentence_segment_count + 1}段已缓存")
                
                self.first_sentence_segment_count += 1
            else:
                # 非第一句话：全部缓存，启动定时发送
                self.opus_datas_cache.extend(opus_datas)
                logger.bind(tag=TAG).debug(f"非第一句话音频段已缓存，当前缓存大小: {len(self.opus_datas_cache)}")
                
                # 如果是后续句子且有缓存数据，启动定时发送
                if self.opus_datas_cache and not self.cache_timer:
                    self._start_cache_timer()
                    logger.bind(tag=TAG).debug("启动后续句子定时发送机制")
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"处理音频数据失败: {str(e)}")
    
    def _flush_cached_audio(self, is_final=False):
        """发送缓存的音频数据"""
        try:
            if not self.opus_datas_cache:
                logger.bind(tag=TAG).debug("没有缓存的音频数据需要发送")
                return
            
            # 检查客户端是否中止
            if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
                logger.bind(tag=TAG).info("收到打断信息，清空音频缓存")
                self.opus_datas_cache.clear()
                self._stop_cache_timer()
                return
            
            # 确定句子类型
            if self.is_first_sentence and self.first_sentence_segment_count > 6:
                # 第一句话的缓存部分
                sentence_type = SentenceType.FIRST
            elif is_final:
                sentence_type = SentenceType.LAST
            else:
                sentence_type = SentenceType.MIDDLE
            
            # 发送缓存的音频数据
            if self.opus_datas_cache:
                self.tts_provider.tts_audio_queue.put(
                    (sentence_type, self.opus_datas_cache.copy(), None)
                )
                logger.bind(tag=TAG).info(f"发送缓存音频数据，段数: {len(self.opus_datas_cache)}, 类型: {sentence_type}")
                
                # 清空缓存
                self.opus_datas_cache.clear()
            
            # 如果是第一句话结束，标记为非第一句话
            if self.is_first_sentence:
                self.is_first_sentence = False
                logger.bind(tag=TAG).debug("第一句话处理完成，后续为非第一句话")
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"发送缓存音频数据失败: {str(e)}")
    
    def _send_cached_audio_timed(self):
        """定时发送缓存的音频数据（用于后续句子）"""
        if not self.opus_datas_cache or self.is_first_sentence:
            return
            
        try:
            # 检查客户端是否已中断
            if hasattr(self.tts_provider, 'conn') and self.tts_provider.conn.client_abort:
                logger.bind(tag=TAG).info("客户端已中断，停止定时发送")
                self._stop_cache_timer()
                return
                
            # 发送一段缓存的音频
            if self.opus_datas_cache:
                opus_data = self.opus_datas_cache.pop(0)
                logger.bind(tag=TAG).debug("定时发送一段缓存音频")
                
                self.tts_provider.tts_audio_queue.put(
                    (SentenceType.MIDDLE, [opus_data], None)
                )
                
            # 如果还有缓存数据，继续设置定时器
            if self.opus_datas_cache and not self.is_first_sentence:
                self._start_cache_timer()
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"定时发送缓存音频失败: {str(e)}")
            
    def _start_cache_timer(self):
        """启动缓存定时器"""
        if self.cache_timer:
            self.cache_timer.cancel()
        self.cache_timer = threading.Timer(self.cache_send_interval, self._send_cached_audio_timed)
        self.cache_timer.start()
        
    def _stop_cache_timer(self):
        """停止缓存定时器"""
        if self.cache_timer:
            self.cache_timer.cancel()
            self.cache_timer = None
    
    def on_sentence_end(self):
        """句子结束时调用，发送缓存的音频数据"""
        logger.bind(tag=TAG).debug("句子结束，发送缓存的音频数据")
        
        # 停止定时器并发送剩余缓存
        self._stop_cache_timer()
        self._flush_cached_audio()
        
        # 第一句话处理完成后，将状态设置为False
        if self.is_first_sentence:
            self.is_first_sentence = False
            logger.bind(tag=TAG).debug("第一句话处理完成，后续句子将使用定时缓存策略")


class TTSProvider(TTSProviderBase):
    """阿里云DashScope双流式TTS提供者"""
    
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        
        # 检查依赖
        if not dashscope:
            raise ImportError("请安装dashscope库: pip install dashscope")
            
        self.interface_type = InterfaceType.DUAL_STREAM
        
        # 配置参数
        self.api_key = config.get("api_key")
        self.model = config.get("model", "cosyvoice-v2")
        self.voice = config.get("voice", "cosyvoice-v2-prefix-113881176adb43aba3acde2406ebfe0e")
        self.audio_format = config.get("audio_format", "PCM_16000HZ_MONO_16BIT")
        
        # 设置API密钥
        if self.api_key:
            setattr(dashscope, 'api_key', self.api_key)
        
        # 创建Opus编码器 - 使用标准16kHz采样率
        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=16000, channels=1, frame_size_ms=60
        )
        
        # 合成器实例
        self.synthesizer = None
        self.callback = None
        self.session_active = False
        
        # 验证模型密钥
        model_key_msg = check_model_key("TTS", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)
            
    def pcm_to_opus_data(self, pcm_data, is_end=False):
        """将PCM数据转换为Opus格式"""
        try:
            # 不需要手动处理奇数长度，直接传给编码器
            opus_datas = self.opus_encoder.encode_pcm_to_opus(
                pcm_data, end_of_stream=is_end
            )
            return opus_datas
        except Exception as e:
            logger.bind(tag=TAG).error(f"PCM转Opus失败: {str(e)}")
            return []
            
    def tts_text_priority_thread(self):
        """阿里云双流式TTS的文本处理线程"""
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                logger.bind(tag=TAG).debug(
                    f"收到TTS任务｜{message.sentence_type.name} ｜ {message.content_type.name}"
                )
                
                if message.sentence_type == SentenceType.FIRST:
                    self.conn.client_abort = False
                    
                if self.conn.client_abort:
                    logger.bind(tag=TAG).info("收到打断信息，终止TTS文本处理线程")
                    # 立即清空文本队列，防止继续处理
                    while True:
                        try:
                            self.tts_text_queue.get_nowait()
                        except queue.Empty:
                            break
                    # 异步关闭TTS会话
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.close(),
                            loop=self.conn.loop,
                        )
                        future.result(timeout=2)  # 设置超时避免阻塞
                    except Exception as e:
                        logger.bind(tag=TAG).warning(f"打断时关闭TTS会话失败: {e}")
                    break  # 退出循环而不是continue
                    
                if message.sentence_type == SentenceType.FIRST:
                    # 启动会话
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.start_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                        future.result()
                        self.tts_audio_first_sentence = True
                        self.before_stop_play_files.clear()
                        
                        # 重置回调状态，确保每次新会话都从第一句话开始
                        if self.callback:
                            self.callback.is_first_sentence = True
                            self.callback.first_sentence_segment_count = 0
                            self.callback.opus_datas_cache.clear()
                            self.callback._stop_cache_timer()  # 停止之前的定时器
                            logger.bind(tag=TAG).debug("回调状态已重置为第一句话")
                            
                        logger.bind(tag=TAG).info("DashScope TTS会话启动成功")
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"启动TTS会话失败: {str(e)}")
                        continue
                        
                elif ContentType.TEXT == message.content_type:
                    # 在处理文本前检查打断状态
                    if self.conn.client_abort:
                        logger.bind(tag=TAG).info("收到打断信息，跳过文本处理")
                        continue
                        
                    if message.content_detail:
                        try:
                            logger.bind(tag=TAG).debug(
                                f"开始发送TTS文本: {message.content_detail}"
                            )
                            future = asyncio.run_coroutine_threadsafe(
                                self.text_to_speak(message.content_detail, None),
                                loop=self.conn.loop,
                            )
                            future.result()
                            logger.bind(tag=TAG).debug("TTS文本发送成功")
                            
                            # 文本发送完成后，触发句子结束处理（发送缓存的音频）
                            if self.callback:
                                self.callback.on_sentence_end()
                                
                        except Exception as e:
                            logger.bind(tag=TAG).error(f"发送TTS文本失败: {str(e)}")
                            continue
                            
                elif ContentType.FILE == message.content_type:
                    # 在处理文件前检查打断状态
                    if self.conn.client_abort:
                        logger.bind(tag=TAG).info("收到打断信息，跳过文件处理")
                        continue
                        
                    logger.bind(tag=TAG).info(
                        f"添加音频文件到待播放列表: {message.content_file}"
                    )
                    if message.content_file and os.path.exists(message.content_file):
                        file_audio = self._process_audio_file(message.content_file)
                        self.before_stop_play_files.append(
                            (file_audio, message.content_detail)
                        )
                        
                if message.sentence_type == SentenceType.LAST:
                    # 在处理最后一句前检查打断状态
                    if self.conn.client_abort:
                        logger.bind(tag=TAG).info("收到打断信息，跳过LAST句子处理")
                        continue
                        
                    # 参考火山双流式的处理方式：收到LAST消息时调用streaming_complete结束合成
                    try:
                        logger.bind(tag=TAG).info("收到LAST句子，开始结束语音合成...")
                        if self.synthesizer and self.session_active:
                            # 调用streaming_complete方法结束语音合成
                            self.synthesizer.streaming_complete()
                            logger.bind(tag=TAG).info("语音合成结束请求已发送")
                        
                        # 设置标志，让会话在TTS合成完成后结束
                        if self.callback:
                            self.callback.should_finish_session = True
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"结束语音合成失败: {str(e)}")
                        
            except queue.Empty:
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"处理TTS文本失败: {str(e)}, 类型: {type(e).__name__}, 堆栈: {traceback.format_exc()}"
                )
                continue
                
    async def text_to_speak(self, text, _):
        """发送文本进行语音合成"""
        try:
            # 检查客户端是否中止
            if self.conn.client_abort:
                logger.bind(tag=TAG).info("收到打断信息，跳过文本合成")
                return
            
            if not self.synthesizer or not self.session_active:
                logger.bind(tag=TAG).warning("TTS会话未激活，跳过文本合成")
                return
                
            # 清理文本
            text = MarkdownCleaner.clean_markdown(text)
            if not text.strip():
                return
                
            logger.bind(tag=TAG).debug(f"发送文本到DashScope: {text}")
            
            # 流式发送文本
            self.synthesizer.streaming_call(text)
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"文本转语音失败: {str(e)}")
            raise
            
    async def start_session(self, session_id):
        """启动TTS会话"""
        logger.bind(tag=TAG).info(f"开始DashScope TTS会话～～{session_id}")
        try:
            # 关闭之前的会话
            if self.synthesizer:
                await self.close()
                
            # 创建回调实例
            self.callback = DashScopeCallback(self)
            
            # 获取音频格式
            audio_format = getattr(AudioFormat, self.audio_format, AudioFormat.PCM_16000HZ_MONO_16BIT)
            
            # 创建合成器实例
            self.synthesizer = SpeechSynthesizer(
                model=self.model,
                voice=self.voice,
                format=audio_format,
                callback=self.callback,
            )
            
            self.session_active = True
            logger.bind(tag=TAG).info("DashScope TTS会话启动成功")
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"启动DashScope TTS会话失败: {str(e)}")
            await self.close()
            raise
            
    async def finish_session(self, session_id):
        """结束TTS会话（兼容性方法）"""
        logger.bind(tag=TAG).info(f"关闭DashScope TTS会话～～{session_id}")
        # 注意：在新的实现中，streaming_complete在收到LAST消息时就已经调用
        # 这里主要用于兼容性和异常情况的处理
        await self.close()
            
    async def close(self):
        """资源清理方法"""
        try:
            self.session_active = False
            
            # 如果是因为打断而关闭，立即清空音频队列
            if hasattr(self, 'conn') and self.conn.client_abort:
                logger.bind(tag=TAG).info("因打断而关闭TTS会话，清空音频队列")
                # 清空音频队列，防止继续播放
                while True:
                    try:
                        self.tts_audio_queue.get_nowait()
                    except:
                        break
                logger.bind(tag=TAG).info(f"音频队列已清空，剩余大小: {self.tts_audio_queue.qsize()}")
            
            if self.synthesizer:
                try:
                    # 如果是因为打断而关闭，尝试停止合成
                    if hasattr(self, 'conn') and self.conn.client_abort:
                        # 尝试停止当前合成
                        if hasattr(self.synthesizer, 'streaming_complete'):
                            self.synthesizer.streaming_complete()
                    
                    # 尝试正常关闭合成器
                    if hasattr(self.synthesizer, 'close'):
                        self.synthesizer.close()
                except Exception as close_e:
                    logger.bind(tag=TAG).warning(f"关闭合成器时发生错误: {close_e}")
                self.synthesizer = None
                
            self.callback = None
            logger.bind(tag=TAG).info("DashScope TTS资源清理完成")
            
        except Exception as e:
            logger.bind(tag=TAG).warning(f"DashScope TTS资源清理时发生错误: {e}")
            
    def _audio_play_priority_thread(self):
        """重写音频播放线程，添加打断检查"""
        while not self.conn.stop_event.is_set():
            text = None
            try:
                try:
                    sentence_type, audio_datas, text = self.tts_audio_queue.get(
                        timeout=1
                    )
                except queue.Empty:
                    if self.conn.stop_event.is_set():
                        break
                    continue
                
                # 检查客户端是否中止
                if self.conn.client_abort:
                    logger.bind(tag=TAG).info("收到打断信息，跳过音频播放")
                    # 清空剩余的音频队列
                    while True:
                        try:
                            self.tts_audio_queue.get_nowait()
                        except queue.Empty:
                            break
                    logger.bind(tag=TAG).info("音频队列已清空，停止播放")
                    break
                
                future = asyncio.run_coroutine_threadsafe(
                    sendAudioMessage(self.conn, sentence_type, audio_datas, text),
                    self.conn.loop,
                )
                future.result()
                if self.conn.max_output_size > 0 and text:
                    add_device_output(self.conn.headers.get("device-id"), len(text))
                enqueue_tts_report(self.conn, text, audio_datas)
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"audio_play_priority priority_thread: {text} {e}"
                )
                # 如果发生异常且是因为打断，退出循环
                if self.conn.client_abort:
                    break
    
    def to_tts(self, text: str) -> list:
        """同步TTS方法（用于兼容）"""
        try:
            # 对于双流式TTS，这个方法主要用于兼容性
            # 实际的流式处理在text_to_speak中进行
            logger.bind(tag=TAG).debug(f"同步TTS调用: {text}")
            return []
        except Exception as e:
            logger.bind(tag=TAG).error(f"同步TTS失败: {str(e)}")
            return []