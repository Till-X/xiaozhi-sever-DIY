# coding=utf-8
import uuid
import os
from datetime import datetime
from core.utils.util import check_model_key
from core.providers.tts.base import TTSProviderBase
from config.logger import setup_logging

try:
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer
except ImportError:
    dashscope = None
    SpeechSynthesizer = None

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    """阿里云DashScope非流式TTS提供者"""
    
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        
        # 检查依赖
        if dashscope is None or SpeechSynthesizer is None:
            raise ImportError("请安装dashscope库: pip install dashscope")
        
        # 配置参数
        self.api_key = config.get("api_key")
        self.model = config.get("model", "cosyvoice-v2")
        
        if config.get("private_voice"):
            self.voice = config.get("private_voice")
        else:
            self.voice = config.get("voice", "longxiaochun_v2")
        
        self.audio_file_type = config.get("format", "mp3")
        
        # 语速参数处理
        speech_rate = config.get("speech_rate", "1.0")
        self.speech_rate = float(speech_rate) if speech_rate else 1.0
        # 确保语速在有效范围内
        if self.speech_rate < 0.5:
            self.speech_rate = 0.5
        elif self.speech_rate > 2.0:
            self.speech_rate = 2.0
        
        # 设置API Key
        if self.api_key:
            dashscope.api_key = self.api_key
        
        # 检查模型密钥
        model_key_msg = check_model_key("TTS", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)
    
    def generate_filename(self, extension=None):
        """生成音频文件名"""
        if extension is None:
            extension = f".{self.audio_file_type}"
        return os.path.join(
            self.output_file,
            f"tts-{datetime.now().date()}@{uuid.uuid4().hex}{extension}",
        )
    
    async def text_to_speak(self, text, output_file):
        """文本转语音"""
        try:
            # 实例化SpeechSynthesizer
            synthesizer = SpeechSynthesizer(
                model=self.model, 
                voice=self.voice,
                speech_rate=self.speech_rate
            )
            
            # 发送待合成文本，获取二进制音频
            audio_data = synthesizer.call(text)
            
            if audio_data:
                if output_file:
                    # 保存到指定文件
                    with open(output_file, 'wb') as f:
                        f.write(audio_data)
                    logger.bind(tag=TAG).info(f"音频已保存到: {output_file}")
                else:
                    # 直接返回音频数据
                    return audio_data
            else:
                raise Exception("音频合成失败，返回数据为空")
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"DashScope TTS错误: {e}")
            raise Exception(f"{__name__} error: {e}")