import os
import re
import time
import random
import difflib
import traceback
from pathlib import Path
from core.handle.sendAudioHandle import send_stt_message
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType

TAG = __name__

MUSIC_CACHE = {}

play_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "唱歌、听歌、播放音乐的方法。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "歌曲名称，如果用户没有指定具体歌名则为'random', 明确指定的时返回音乐的名字 示例: ```用户:播放两只老虎\n参数：两只老虎``` ```用户:播放音乐 \n参数：random ```",
                }
            },
            "required": ["song_name"],
        },
    },
}


@register_function("play_music", play_music_function_desc, ToolType.SYSTEM_CTL)
def play_music(conn, song_name: str):
    try:
        music_intent = (
            f"播放音乐 {song_name}" if song_name != "random" else "随机播放音乐"
        )

        # 检查事件循环状态
        if not conn.loop.is_running():
            conn.logger.bind(tag=TAG).error("事件循环未运行，无法提交任务")
            return ActionResponse(
                action=Action.RESPONSE, result="系统繁忙", response="请稍后再试"
            )

        # 提交异步任务
        task = conn.loop.create_task(
            handle_music_command(conn, music_intent)  # 封装异步逻辑
        )

        # 非阻塞回调处理
        def handle_done(f):
            try:
                f.result()  # 可在此处理成功逻辑
                conn.logger.bind(tag=TAG).info("播放完成")
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"播放失败: {e}")

        task.add_done_callback(handle_done)

        return ActionResponse(
            action=Action.NONE, result="指令已接收", response="正在为您播放音乐"
        )
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"处理音乐意图错误: {e}")
        return ActionResponse(
            action=Action.RESPONSE, result=str(e), response="播放音乐时出错了"
        )


def _extract_song_name(text):
    """从用户输入中提取歌名"""
    for keyword in ["播放音乐"]:
        if keyword in text:
            parts = text.split(keyword)
            if len(parts) > 1:
                return parts[1].strip()
    return None


def _find_best_match(potential_song, music_files):
    """查找最匹配的歌曲"""
    best_match = None
    highest_ratio = 0

    for music_file in music_files:
        song_name = os.path.splitext(music_file)[0]
        ratio = difflib.SequenceMatcher(None, potential_song, song_name).ratio()
        if ratio > highest_ratio and ratio > 0.4:
            highest_ratio = ratio
            best_match = music_file
    return best_match


def get_music_files(music_dir, music_ext):
    music_dir = Path(music_dir)
    music_files = []
    music_file_names = []
    for file in music_dir.rglob("*"):
        # 判断是否是文件
        if file.is_file():
            # 获取文件扩展名
            ext = file.suffix.lower()
            # 判断扩展名是否在列表中
            if ext in music_ext:
                # 添加相对路径
                music_files.append(str(file.relative_to(music_dir)))
                music_file_names.append(
                    os.path.splitext(str(file.relative_to(music_dir)))[0]
                )
    return music_files, music_file_names


def initialize_music_handler(conn):
    global MUSIC_CACHE
    
    # 根据角色名称生成缓存键，确保不同角色使用不同的音乐缓存
    cache_key = conn.assistant_name if conn.assistant_name else "default"
    
    if cache_key not in MUSIC_CACHE:
        MUSIC_CACHE[cache_key] = {}
        
        if "play_music" in conn.config["plugins"]:
            music_config = conn.config["plugins"]["play_music"]
            base_music_dir = music_config.get("music_dir", "./music")
            music_ext = music_config.get("music_ext", (".mp3", ".wav", ".p3"))
            refresh_time = music_config.get("refresh_time", 60)
        else:
            base_music_dir = "./music"
            music_ext = (".mp3", ".wav", ".p3")
            refresh_time = 60
        
        # 根据角色名称构建音乐目录路径，严格按角色隔离
        if conn.assistant_name:
            role_music_dir = os.path.join(base_music_dir, conn.assistant_name)
            music_dir = os.path.abspath(role_music_dir)
            # 如果角色专属目录不存在，不创建，标记为无效
            if not os.path.exists(music_dir):
                conn.logger.bind(tag=TAG).warning(f"角色专属音乐目录不存在: {music_dir}")
                MUSIC_CACHE[cache_key]["music_dir"] = None
                MUSIC_CACHE[cache_key]["music_files"] = []
                MUSIC_CACHE[cache_key]["music_file_names"] = []
                MUSIC_CACHE[cache_key]["scan_time"] = time.time()
                return MUSIC_CACHE[cache_key]
            else:
                conn.logger.bind(tag=TAG).info(f"使用角色专属音乐目录: {music_dir}")
        else:
            # 未识别到角色名称时，使用default子目录
            default_music_dir = os.path.join(base_music_dir, "default")
            music_dir = os.path.abspath(default_music_dir)
            # 如果默认目录不存在，不创建，标记为无效
            if not os.path.exists(music_dir):
                conn.logger.bind(tag=TAG).warning(f"默认角色音乐目录不存在: {music_dir}")
                MUSIC_CACHE[cache_key]["music_dir"] = None
                MUSIC_CACHE[cache_key]["music_files"] = []
                MUSIC_CACHE[cache_key]["music_file_names"] = []
                MUSIC_CACHE[cache_key]["scan_time"] = time.time()
                return MUSIC_CACHE[cache_key]
            else:
                conn.logger.bind(tag=TAG).info(f"使用默认角色音乐目录: {music_dir}")
        
        MUSIC_CACHE[cache_key]["music_config"] = music_config if "play_music" in conn.config["plugins"] else {}
        MUSIC_CACHE[cache_key]["music_dir"] = music_dir
        MUSIC_CACHE[cache_key]["music_ext"] = music_ext
        MUSIC_CACHE[cache_key]["refresh_time"] = refresh_time
        
        # 获取音乐文件列表
        MUSIC_CACHE[cache_key]["music_files"], MUSIC_CACHE[cache_key]["music_file_names"] = get_music_files(
            MUSIC_CACHE[cache_key]["music_dir"], MUSIC_CACHE[cache_key]["music_ext"]
        )
        MUSIC_CACHE[cache_key]["scan_time"] = time.time()
    
    return MUSIC_CACHE[cache_key]


async def handle_music_command(conn, text):
    music_cache = initialize_music_handler(conn)

    """处理音乐播放指令"""
    clean_text = re.sub(r"[^\w\s]", "", text).strip()
    conn.logger.bind(tag=TAG).debug(f"检查是否是音乐命令: {clean_text}")

    # 检查音乐目录是否存在
    if music_cache["music_dir"] is None or not os.path.exists(music_cache["music_dir"]):
        # 音乐目录不存在，回复未找到曲库
        error_text = "未找到曲库"
        await send_stt_message(conn, error_text)
        conn.dialogue.put(Message(role="assistant", content=error_text))
        
        if conn.intent_type == "intent_llm":
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=conn.sentence_id,
                    sentence_type=SentenceType.FIRST,
                    content_type=ContentType.ACTION,
                )
            )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=error_text,
            )
        )
        if conn.intent_type == "intent_llm":
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=conn.sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )
        return True

    # 刷新音乐文件列表
    if time.time() - music_cache["scan_time"] > music_cache["refresh_time"]:
        music_cache["music_files"], music_cache["music_file_names"] = (
            get_music_files(music_cache["music_dir"], music_cache["music_ext"])
        )
        music_cache["scan_time"] = time.time()

    # 尝试匹配具体歌名
    potential_song = _extract_song_name(clean_text)
    if potential_song:
        best_match = _find_best_match(potential_song, music_cache["music_files"])
        if best_match:
            conn.logger.bind(tag=TAG).info(f"找到最匹配的歌曲: {best_match}")
            await play_local_music(conn, specific_file=best_match)
            return True
        else:
            # 未找到指定歌曲，随机播放一首
            conn.logger.bind(tag=TAG).info(f"未找到歌曲: {potential_song}，随机播放")
            await play_local_music(conn, song_not_found=True, requested_song=potential_song)
            return True
    
    # 检查是否是通用播放音乐命令
    await play_local_music(conn)
    return True


def _get_random_play_prompt(song_name):
    """生成随机播放引导语"""
    # 移除文件扩展名
    clean_name = os.path.splitext(song_name)[0]
    prompts = [
        f"正在为您播放，《{clean_name}》",
        f"请欣赏歌曲，《{clean_name}》",
        f"即将为您播放，《{clean_name}》",
        f"现在为您带来，《{clean_name}》",
        f"让我们一起聆听，《{clean_name}》",
        f"接下来请欣赏，《{clean_name}》",
        f"此刻为您献上，《{clean_name}》",
    ]
    # 直接使用random.choice，不设置seed
    return random.choice(prompts)


async def play_local_music(conn, specific_file=None, song_not_found=False, requested_song=None):
    music_cache = initialize_music_handler(conn)
    """播放本地音乐文件"""
    try:
        if not os.path.exists(music_cache["music_dir"]):
            conn.logger.bind(tag=TAG).error(
                f"音乐目录不存在: " + music_cache["music_dir"]
            )
            return

        # 确保路径正确性
        if specific_file:
            selected_music = specific_file
            music_path = os.path.join(music_cache["music_dir"], specific_file)
        else:
            if not music_cache["music_files"]:
                conn.logger.bind(tag=TAG).error("未找到MP3音乐文件")
                return
            selected_music = random.choice(music_cache["music_files"])
            music_path = os.path.join(music_cache["music_dir"], selected_music)

        if not os.path.exists(music_path):
            conn.logger.bind(tag=TAG).error(f"选定的音乐文件不存在: {music_path}")
            return
        
        # 根据是否找到歌曲生成不同的提示语
        if song_not_found and requested_song:
            clean_name = os.path.splitext(selected_music)[0]
            text = f"未找到歌曲，随机播放《{clean_name}》"
        else:
            text = _get_random_play_prompt(selected_music)
        
        await send_stt_message(conn, text)
        conn.dialogue.put(Message(role="assistant", content=text))

        if conn.intent_type == "intent_llm":
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=conn.sentence_id,
                    sentence_type=SentenceType.FIRST,
                    content_type=ContentType.ACTION,
                )
            )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=text,
            )
        )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.FILE,
                content_file=music_path,
            )
        )
        if conn.intent_type == "intent_llm":
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=conn.sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )

    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"播放音乐失败: {str(e)}")
        conn.logger.bind(tag=TAG).error(f"详细错误: {traceback.format_exc()}")
