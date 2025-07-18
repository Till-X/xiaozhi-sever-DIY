# 阿里云百炼非流式TTS集成指南

本文档介绍如何在小智服务器中集成和使用阿里云百炼（DashScope）非流式TTS功能。

## 功能特点

- **非流式合成**：一次性返回完整音频，适合短文本场景
- **高质量音色**：支持多种高质量音色选择
- **简单易用**：配置简单，调用方便
- **成本优化**：相比流式TTS，在某些场景下更经济

## 前置条件

1. 安装依赖库：
   ```bash
   pip install dashscope
   ```

2. 获取阿里云DashScope API密钥：
   - 访问 [DashScope控制台](https://dashscope.console.aliyun.com/)
   - 注册并开通语音合成服务
   - 在 [API密钥页面](https://dashscope.console.aliyun.com/apiKey) 获取API Key

## 配置说明

在 `config.yaml` 文件的 `TTS` 部分添加以下配置：

```yaml
TTS:
  DashScopeTTS:
    # 阿里云DashScope非流式TTS服务
    type: dashscope
    # 你的DashScope API密钥
    api_key: "你的DashScope API密钥"
    # 模型名称，支持cosyvoice-v2等
    model: "cosyvoice-v2"
    # 音色ID，可选longxiaochun_v2、longwan_v2等
    voice: "longxiaochun_v2"
    # 音频格式，支持mp3、wav等
    format: "mp3"
    # 语速：0.5-2.0，1.0为默认语速
    speech_rate: 1.0
    output_dir: tmp/
```

### 配置参数说明

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| `type` | TTS类型标识 | `dashscope_simple` | 固定值 |
| `api_key` | DashScope API密钥 | 无 | 从控制台获取 |
| `model` | 语音合成模型 | `cosyvoice-v2` | `cosyvoice-v2` 等 |
| `voice` | 音色ID | `longxiaochun_v2` | 见音色列表 |
| `format` | 音频格式 | `mp3` | `mp3`, `wav` |
| `speech_rate` | 语速 | `1.0` | 取值范围：0.5-2.0，1.0为默认语速 |
| `output_dir` | 音频输出目录 | `tmp/` | 任意有效路径 |

### 可用音色

- `longxiaochun_v2` - 龙小春（女声）
- `longwan_v2` - 龙婉（女声）
- 更多音色请参考 [DashScope文档](https://help.aliyun.com/zh/dashscope/)

## 使用方法

### 1. 在配置中选择TTS模块

在 `config.yaml` 的 `selected_module` 部分设置：

```yaml
selected_module:
  TTS: DashScopeTTS
```

### 2. 代码中使用

```python
from core.providers.tts.dashscope_simple import TTSProvider

# 初始化TTS提供者
config = {
    "api_key": "你的API密钥",
    "model": "cosyvoice-v2",
    "voice": "longxiaochun_v2",
    "format": "mp3",
    "output_dir": "tmp/"
}

tts_provider = TTSProvider(config, delete_audio_file=False)

# 文本转语音
text = "你好，这是阿里云百炼TTS测试"
output_file = "output.mp3"

# 保存到文件
await tts_provider.text_to_speak(text, output_file)

# 或直接获取音频数据
audio_data = await tts_provider.text_to_speak(text, None)
```

## 测试

运行测试脚本验证功能：

```bash
cd /path/to/xiaozhi-server
python test_dashscope_simple_tts.py
```

测试脚本会：
1. 加载配置文件
2. 初始化TTS提供者
3. 执行语音合成
4. 验证输出结果

## 与流式TTS的区别

| 特性 | 非流式TTS | 流式TTS |
|------|-----------|----------|
| **延迟** | 较高（需等待完整合成） | 较低（边合成边播放） |
| **适用场景** | 短文本、离线处理 | 长文本、实时对话 |
| **资源占用** | 内存占用较高 | 内存占用较低 |
| **实现复杂度** | 简单 | 复杂 |
| **成本** | 按次计费 | 按时长计费 |

## 故障排除

### 常见问题

1. **ImportError: 缺少dashscope库**
   ```bash
   pip install dashscope
   ```

2. **API密钥错误**
   - 检查API密钥是否正确
   - 确认已开通语音合成服务
   - 检查账户余额

3. **音频文件生成失败**
   - 检查输出目录权限
   - 确认磁盘空间充足
   - 查看错误日志

4. **音色不支持**
   - 检查音色ID是否正确
   - 参考官方文档获取最新音色列表

### 日志调试

启用DEBUG日志查看详细信息：

```yaml
log:
  log_level: DEBUG
```

## 性能优化建议

1. **文本长度控制**：非流式TTS适合短文本（建议<200字符）
2. **并发控制**：避免同时发起过多TTS请求
3. **缓存策略**：对相同文本可考虑缓存音频结果
4. **格式选择**：MP3格式文件更小，WAV格式质量更高

## 更新日志

- **v1.0.0** (2024-01-XX)
  - 初始版本发布
  - 支持基础非流式TTS功能
  - 支持多种音色和格式

## 相关链接

- [阿里云DashScope官网](https://dashscope.aliyuncs.com/)
- [DashScope文档](https://help.aliyun.com/zh/dashscope/)
- [API密钥管理](https://dashscope.console.aliyun.com/apiKey)
- [小智服务器项目](https://github.com/xinnan-tech/xiaozhi-esp32-server)