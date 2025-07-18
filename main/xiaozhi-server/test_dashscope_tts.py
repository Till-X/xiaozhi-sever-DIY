#!/usr/bin/env python3
# coding=utf-8
"""
阿里云DashScope TTS集成测试脚本

使用方法：
1. 在config.yaml中配置DashScope TTS的API密钥
2. 运行此脚本测试TTS功能

python test_dashscope_tts.py
"""

import asyncio
import sys
import os
import wave
import numpy as np
from typing import List

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.config_loader import load_config
from core.providers.tts.dashscope import TTSProvider
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
import queue
import threading
import time

try:
    from opuslib_next import Decoder
except ImportError:
    Decoder = None
    print("⚠️ 警告: opuslib_next未安装，无法进行Opus解码验证")


class AudioVerifier:
    """音频验证工具类"""
    
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.decoder = None
        self.collected_audio = []
        
        if Decoder:
            try:
                self.decoder = Decoder(sample_rate, channels)
                print("✅ Opus解码器初始化成功")
            except Exception as e:
                print(f"❌ Opus解码器初始化失败: {e}")
                self.decoder = None
        
    def decode_opus_to_pcm(self, opus_data_list: List[bytes]) -> bytes:
        """解码Opus数据为PCM"""
        if not self.decoder or not opus_data_list:
            return b''
            
        pcm_data = bytearray()
        
        try:
            for opus_packet in opus_data_list:
                if opus_packet:
                    # 解码Opus包为PCM数据
                    decoded = self.decoder.decode(opus_packet, frame_size=960)  # 60ms at 16kHz
                    pcm_data.extend(decoded)
        except Exception as e:
            print(f"❌ Opus解码失败: {e}")
            
        return bytes(pcm_data)
    
    def save_pcm_as_wav(self, pcm_data: bytes, filename: str):
        """保存PCM数据为WAV文件"""
        if not pcm_data:
            print("⚠️ 没有PCM数据可保存")
            return
            
        try:
            # 将字节数据转换为numpy数组
            audio_array = np.frombuffer(pcm_data, dtype=np.int16)
            
            # 保存为WAV文件
            with wave.open(filename, 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(pcm_data)
                
            file_size = len(pcm_data)
            duration = len(audio_array) / self.sample_rate
            print(f"🎵 音频已保存到 {filename}")
            print(f"   文件大小: {file_size} 字节")
            print(f"   音频时长: {duration:.2f} 秒")
            print(f"   采样率: {self.sample_rate} Hz")
            print(f"   声道数: {self.channels}")
            
        except Exception as e:
            print(f"❌ 保存WAV文件失败: {e}")
    
    def save_audio_for_verification(self, opus_data_list: List[bytes], filename="test_output.wav"):
        """保存音频数据用于验证"""
        if opus_data_list:
            # 解码Opus数据并保存为WAV文件
            pcm_data = self.decode_opus_to_pcm(opus_data_list)
            if pcm_data:
                self.save_pcm_as_wav(pcm_data, filename)
            else:
                print("⚠️ 解码后的PCM数据为空")
        else:
            print("⚠️ 没有Opus数据可验证")
    
    def collect_audio_data(self, opus_data_list: List[bytes]):
        """收集音频数据"""
        if opus_data_list:
            self.collected_audio.extend(opus_data_list)
    
    def save_collected_audio(self, filename="collected_audio.wav"):
        """保存收集的所有音频数据"""
        if self.collected_audio:
            self.save_audio_for_verification(self.collected_audio, filename)
            print(f"📊 总共收集了 {len(self.collected_audio)} 个音频包")
        else:
            print("⚠️ 没有收集到音频数据")


class MockConnection:
    """模拟连接对象"""
    def __init__(self):
        self.stop_event = threading.Event()
        self.client_abort = False
        self.sentence_id = "test_session_123"
        self.loop = asyncio.get_event_loop()
        self.headers = {"device-id": "test_device"}
        self.max_output_size = 0


async def test_dashscope_tts():
    """测试DashScope TTS功能"""
    print("🚀 开始测试阿里云DashScope TTS集成...")
    
    try:
        # 加载配置
        config = load_config()
        dashscope_config = config.get("TTS", {}).get("DashScopeTTS", {})
        
        if not dashscope_config:
            print("❌ 错误：未找到DashScopeTTS配置")
            return False
            
        api_key = dashscope_config.get("api_key")
        if not api_key or api_key == "你的DashScope API密钥":
            print("❌ 错误：请在config.yaml中配置有效的DashScope API密钥")
            return False
            
        print(f"✅ 配置加载成功")
        print(f"   模型: {dashscope_config.get('model')}")
        print(f"   音色: {dashscope_config.get('voice')}")
        print(f"   音频格式: {dashscope_config.get('audio_format')}")
        
        # 创建TTS提供者
        tts_provider = TTSProvider(dashscope_config, delete_audio_file=True)
        print("✅ TTS提供者创建成功")
        
        # 创建音频验证器
        audio_verifier = AudioVerifier(sample_rate=16000, channels=1)
        
        # 创建模拟连接
        mock_conn = MockConnection()
        tts_provider.conn = mock_conn
        
        # 启动音频播放线程（模拟）
        def mock_audio_thread():
            """模拟音频播放线程，包含音频验证功能"""
            frame_count = 0
            while not mock_conn.stop_event.is_set():
                try:
                    sentence_type, audio_datas, text = tts_provider.tts_audio_queue.get(timeout=1)
                    frame_count += len(audio_datas)
                    print(f"🎵 接收到音频数据: {len(audio_datas)} 帧, 文本: {text}")
                    
                    # 收集音频数据用于验证
                    if audio_datas:
                        audio_verifier.collect_audio_data(audio_datas)
                        
                        # 每收集到一定数量的帧就保存一次（可选）
                        if frame_count % 50 == 0:
                            print(f"📊 已收集 {frame_count} 帧音频数据")
                    
                    if sentence_type == SentenceType.LAST:
                        print("🏁 音频流结束")
                        # 保存所有收集的音频数据
                        print("\n💾 正在保存音频验证文件...")
                        audio_verifier.save_collected_audio("dashscope_tts_output.wav")
                        break
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"❌ 音频处理错误: {e}")
                    
        audio_thread = threading.Thread(target=mock_audio_thread, daemon=True)
        audio_thread.start()
        
        # 启动文本处理线程
        text_thread = threading.Thread(target=tts_provider.tts_text_priority_thread, daemon=True)
        text_thread.start()
        
        # 测试文本列表
        test_texts = [
            "你好，我是阿里云DashScope双流式TTS。",
            "这是一个测试语音合成的例子。",
            "双流式TTS可以实现低延迟的实时语音合成。",
            "感谢您使用我们的服务！"
        ]
        
        print("\n🎤 开始语音合成测试...")
        
        # 发送FIRST消息
        first_message = TTSMessageDTO(
            sentence_id="test_001",
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.TEXT,
            content_detail=None
        )
        tts_provider.tts_text_queue.put(first_message)
        
        # 等待会话启动
        await asyncio.sleep(2)
        
        # 发送文本消息
        for i, text in enumerate(test_texts):
            print(f"📝 发送文本 {i+1}: {text}")
            text_message = TTSMessageDTO(
                sentence_id=f"test_{i+2:03d}",
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=text
            )
            tts_provider.tts_text_queue.put(text_message)
            await asyncio.sleep(0.5)  # 模拟流式输入
            
        # 发送LAST消息
        last_message = TTSMessageDTO(
            sentence_id="test_999",
            sentence_type=SentenceType.LAST,
            content_type=ContentType.TEXT,
            content_detail=None
        )
        tts_provider.tts_text_queue.put(last_message)
        
        # 等待处理完成
        print("⏳ 等待语音合成完成...")
        await asyncio.sleep(10)
        
        # 停止测试
        mock_conn.stop_event.set()
        await tts_provider.close()
        
        print("\n✅ DashScope TTS测试完成！")
        return True
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("💡 请确保已安装dashscope库: pip install dashscope")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("🎯 阿里云DashScope双流式TTS集成测试")
    print("=" * 60)
    
    # 运行测试
    success = asyncio.run(test_dashscope_tts())
    
    if success:
        print("\n🎉 测试成功！DashScope TTS已成功集成到项目中。")
        print("\n🎵 音频验证说明：")
        print("• 如果生成了 dashscope_tts_output.wav 文件，可以播放验证音频质量")
        print("• 音频文件采用16kHz采样率，单声道，16位深度")
        print("• 可以使用任何音频播放器播放该文件")
        print("\n📋 使用说明：")
        print("1. 在config.yaml中将TTS设置为: DashScopeTTS")
        print("2. 配置有效的DashScope API密钥")
        print("3. 根据需要调整模型、音色等参数")
        print("4. 重启服务即可使用双流式TTS功能")
    else:
        print("\n💥 测试失败！请检查配置和依赖。")
        sys.exit(1)