-- 添加阿里百炼DashScope双流式TTS模型供应器
delete from `ai_model_provider` where id = 'SYSTEM_TTS_DashScopeDS';
INSERT INTO `ai_model_provider` (`id`, `model_type`, `provider_code`, `name`, `fields`, `sort`, `creator`, `create_date`, `updater`, `update_date`) VALUES
('SYSTEM_TTS_DashScopeDS', 'TTS', 'dashscope_double_stream', '阿里百炼双流式语音合成', '[{"key":"api_key","label":"API密钥","type":"string"},{"key":"model","label":"模型名称","type":"string"},{"key":"voice","label":"默认音色","type":"string"},{"key":"audio_format","label":"音频格式","type":"string"},{"key":"speech_rate","label":"语速","type":"string"},{"key":"output_dir","label":"输出目录","type":"string"}]', 17, 1, NOW(), 1, NOW());

-- 添加阿里百炼DashScope双流式TTS模型配置
delete from `ai_model_config` where id = 'TTS_DashScopeDS';
INSERT INTO `ai_model_config` VALUES ('TTS_DashScopeDS', 'TTS', 'DashScopeDS', '阿里百炼双流式语音合成', 0, 1, '{"type": "dashscope_double_stream", "api_key": "你的API密钥", "model": "cosyvoice-v2", "voice": "longxiaochun_v2", "audio_format": "PCM_22050HZ_MONO_16BIT", "speech_rate": "1.0", "output_dir": "tmp/"}', NULL, NULL, 17, NULL, NULL, NULL, NULL);

-- 添加阿里百炼DashScope双流式TTS音色配置
delete from `ai_tts_voice` where id = 'TTS_DashScopeDS_0001';
INSERT INTO `ai_tts_voice` (`id`, `tts_model_id`, `name`, `tts_voice`, `languages`, `voice_demo`, `remark`, `sort`, `creator`, `create_date`, `updater`, `update_date`) VALUES ('TTS_DashScopeDS_0001', 'TTS_DashScopeDS', '龙小春（双流式）', 'longxiaochun_v2', '中文', NULL, NULL, 1, NULL, NULL, NULL, NULL);