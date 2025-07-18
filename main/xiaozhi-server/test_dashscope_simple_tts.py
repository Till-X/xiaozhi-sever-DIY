#!/usr/bin/env python3
# coding=utf-8
"""
测试阿里云DashScope非流式TTS功能
"""

import os
import sys
import yaml
import asyncio
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.providers.tts.dashscope import TTSProvider
from config.logger import setup_logging

logger = setup_logging()


def load_config():
    """加载配置文件"""
    config_path = project_root / "config.yaml"
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        return None
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


async def test_dashscope_simple_tts():
    """测试DashScope非流式TTS功能"""
    print("🚀 开始测试阿里云DashScope非流式TTS...")
    
    try:
        # 加载配置
        config = load_config()
        if not config:
            return
        
        # 获取DashScope配置
        dashscope_config = config.get("TTS", {}).get("DashScopeTTS", {})
        if not dashscope_config:
            print("❌ 未找到DashScope TTS配置")
            return
        
        # 测试配置
        test_config = {
            "api_key": dashscope_config.get("api_key"),
            "model": dashscope_config.get("model", "cosyvoice-v2"),
            "voice": dashscope_config.get("voice", "longxiaochun_v2"),
            "format": "mp3",
            "speech_rate": 1.2,  # 测试1.2倍语速
            "output_dir": "tmp/"
        }
        
        print(f"📋 配置信息:")
        print(f"   模型: {test_config['model']}")
        print(f"   音色: {test_config['voice']}")
        print(f"   格式: {test_config['format']}")
        
        # 创建输出目录
        os.makedirs(test_config["output_dir"], exist_ok=True)
        
        # 初始化TTS提供者
        print("\n🔧 初始化TTS提供者...")
        tts_provider = TTSProvider(test_config, delete_audio_file=False)
        
        # 测试文本
        test_text = "你好，这是阿里云百炼TTS的测试。今天天气怎么样？"
        print(f"\n📝 测试文本: {test_text}")
        
        # 生成音频文件名
        output_file = tts_provider.generate_filename(".mp3")
        print(f"\n🎵 生成音频文件: {output_file}")
        
        # 执行TTS转换
        print("\n⚡ 开始语音合成...")
        start_time = asyncio.get_event_loop().time()
        
        await tts_provider.text_to_speak(test_text, output_file)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        # 检查结果
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            print(f"\n✅ 语音合成成功!")
            print(f"   文件路径: {output_file}")
            print(f"   文件大小: {file_size} 字节")
            print(f"   耗时: {duration:.2f} 秒")
            
            # 测试直接返回音频数据
            print("\n🔄 测试直接返回音频数据...")
            audio_data = await tts_provider.text_to_speak(test_text, None)
            if audio_data:
                print(f"✅ 直接返回音频数据成功，大小: {len(audio_data)} 字节")
            else:
                print("❌ 直接返回音频数据失败")
                
        else:
            print(f"❌ 语音合成失败，文件未生成: {output_file}")
            
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_dashscope_simple_tts())