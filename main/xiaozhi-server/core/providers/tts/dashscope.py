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
        self.audio_buffer = bytearray()
        self.is_first_data = True
        
    def on_open(self):
        logger.bind(tag=TAG).info("DashScope TTS连接建立")
        
    def on_complete(self):
        logger.bind(tag=TAG).info("DashScope TTS语音合成完成")
        # 发送最后的音频数据
        if self.audio_buffer:
            self._process_audio_data(self.audio_buffer, is_last=True)
            self.audio_buffer.clear()
            
    def on_error(self, message: str):
        logger.bind(tag=TAG).error(f"DashScope TTS语音合成出现异常：{message}")
        
    def on_close(self):
        logger.bind(tag=TAG).info("DashScope TTS连接关闭")
        
    def on_event(self, message):
        pass
        
    def on_data(self, data: bytes) -> None:
        """接收音频数据回调"""
        logger.bind(tag=TAG).debug(f"接收到音频数据，长度：{len(data)}")
        
        # 将音频数据添加到缓冲区
        self.audio_buffer.extend(data)
        
        # 对于首句，快速发送小段音频以降低延迟
        if self.is_first_data and len(self.audio_buffer) >= 4096:  # 4KB阈值
            self._process_audio_data(self.audio_buffer[:4096], is_first=True)
            self.audio_buffer = self.audio_buffer[4096:]
            self.is_first_data = False
        elif len(self.audio_buffer) >= 8192:  # 8KB阈值
            self._process_audio_data(self.audio_buffer, is_first=False)
            self.audio_buffer.clear()
            
    def _process_audio_data(self, audio_data, is_first=False, is_last=False):
        """处理音频数据并转换为Opus格式"""
        try:
            # 将PCM数据转换为Opus格式
            opus_datas = self.tts_provider.pcm_to_opus_data(audio_data)
            
            if is_first:
                sentence_type = SentenceType.FIRST
            elif is_last:
                sentence_type = SentenceType.LAST
            else:
                sentence_type = SentenceType.MIDDLE
                
            # 将音频数据放入队列
            self.tts_provider.tts_audio_queue.put(
                (sentence_type, opus_datas, None)
            )
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"处理音频数据失败: {str(e)}")


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
        self.audio_format = config.get("audio_format", "PCM_22050HZ_MONO_16BIT")
        
        # 设置API密钥
        if self.api_key:
            dashscope.api_key = self.api_key
        
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
            
    def pcm_to_opus_data(self, pcm_data):
        """将PCM数据转换为Opus格式"""
        try:
            # 确保PCM数据长度是偶数（16位音频）
            if len(pcm_data) % 2 != 0:
                pcm_data = pcm_data[:-1]
                
            # 转换为Opus格式
            opus_datas = self.opus_encoder.encode_pcm_to_opus(
                pcm_data, end_of_stream=False
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
                    continue
                    
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
                        logger.bind(tag=TAG).info("DashScope TTS会话启动成功")
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"启动TTS会话失败: {str(e)}")
                        continue
                        
                elif ContentType.TEXT == message.content_type:
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
                        except Exception as e:
                            logger.bind(tag=TAG).error(f"发送TTS文本失败: {str(e)}")
                            continue
                            
                elif ContentType.FILE == message.content_type:
                    logger.bind(tag=TAG).info(
                        f"添加音频文件到待播放列表: {message.content_file}"
                    )
                    if message.content_file and os.path.exists(message.content_file):
                        file_audio = self._process_audio_file(message.content_file)
                        self.before_stop_play_files.append(
                            (file_audio, message.content_detail)
                        )
                        
                if message.sentence_type == SentenceType.LAST:
                    try:
                        logger.bind(tag=TAG).info("开始结束TTS会话...")
                        future = asyncio.run_coroutine_threadsafe(
                            self.finish_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                        future.result()
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"结束TTS会话失败: {str(e)}")
                        continue
                        
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
        """结束TTS会话"""
        logger.bind(tag=TAG).info(f"关闭DashScope TTS会话～～{session_id}")
        try:
            if self.synthesizer and self.session_active:
                # 结束流式合成
                self.synthesizer.streaming_complete()
                logger.bind(tag=TAG).info("DashScope TTS会话结束请求已发送")
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"关闭DashScope TTS会话失败: {str(e)}")
        finally:
            await self.close()
            
    async def close(self):
        """资源清理方法"""
        try:
            self.session_active = False
            
            if self.synthesizer:
                try:
                    # 尝试正常关闭合成器
                    if hasattr(self.synthesizer, 'close'):
                        self.synthesizer.close()
                except:
                    pass
                self.synthesizer = None
                
            self.callback = None
            logger.bind(tag=TAG).info("DashScope TTS资源清理完成")
            
        except Exception as e:
            logger.bind(tag=TAG).warning(f"DashScope TTS资源清理时发生错误: {e}")
            
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