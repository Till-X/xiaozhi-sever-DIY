-- 添加阿里百炼DashScope TTS模型供应器
delete from `ai_model_provider` where id = 'SYSTEM_TTS_DashScopeTTS';
INSERT INTO `ai_model_provider` (`id`, `model_type`, `provider_code`, `name`, `fields`, `sort`, `creator`, `create_date`, `updater`, `update_date`) VALUES
('SYSTEM_TTS_DashScopeTTS', 'TTS', 'dashscope', '阿里百炼语音合成', '[{"key":"api_key","label":"API密钥","type":"string"},{"key":"model","label":"模型名称","type":"string"},{"key":"voice","label":"默认音色","type":"string"},{"key":"format","label":"音频格式","type":"string"},{"key":"speech_rate","label":"语速","type":"string"},{"key":"output_dir","label":"输出目录","type":"string"}]', 16, 1, NOW(), 1, NOW());

-- 添加阿里百炼DashScope TTS模型配置
delete from `ai_model_config` where id = 'TTS_DashScopeTTS';
INSERT INTO `ai_model_config` VALUES ('TTS_DashScopeTTS', 'TTS', 'DashScopeTTS', '阿里百炼语音合成', 0, 1, '{"type": "dashscope", "api_key": "你的API密钥", "model": "cosyvoice-v2", "voice": "longxiaochun_v2", "format": "mp3", "speech_rate": "1.0", "output_dir": "tmp/"}', NULL, NULL, 16, NULL, NULL, NULL, NULL);

-- 添加阿里百炼DashScope TTS音色配置
delete from `ai_tts_voice` where id = 'TTS_DashScopeTTS_0001';
INSERT INTO `ai_tts_voice` (`id`, `tts_model_id`, `name`, `tts_voice`, `languages`, `voice_demo`, `remark`, `sort`, `creator`, `create_date`, `updater`, `update_date`) VALUES ('TTS_DashScopeTTS_0001', 'TTS_DashScopeTTS', '龙小春', 'longxiaochun_v2', '中文', NULL, NULL, 1, NULL, NULL, NULL, NULL);