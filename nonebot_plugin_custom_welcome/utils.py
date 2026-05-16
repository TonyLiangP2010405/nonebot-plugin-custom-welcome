import time
from pathlib import Path
from typing import Optional

import httpx
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.log import logger
from nonebot.permission import SUPERUSER

from .data import get_group_image_dir

# 群防重复记录: {group_id: last_trigger_time}
_welcome_cooldown: dict = {}


async def check_permission(bot: Bot, event: GroupMessageEvent) -> bool:
    """检查用户是否有权限（群主、管理员、SUPERUSER）"""
    # SUPERUSER 始终有权限
    if await SUPERUSER(bot, event):
        return True
    # 群角色检查
    return event.sender.role in ("owner", "admin")


def is_cooldown(group_id: str, cooldown_seconds: int = 30) -> bool:
    """检查群是否在冷却中，如果在冷却中返回 True，否则更新冷却时间并返回 False"""
    now = time.time()
    last_time = _welcome_cooldown.get(group_id, 0)
    if now - last_time < cooldown_seconds:
        return True
    _welcome_cooldown[group_id] = now
    return False


def extract_image_url(message: Message) -> Optional[str]:
    """从消息中提取图片 URL"""
    for seg in message:
        if seg.type == "image":
            url = seg.data.get("url")
            if url:
                return url
    return None


def extract_image_file(message: Message) -> Optional[str]:
    """从消息中提取图片 file 字段"""
    for seg in message:
        if seg.type == "image":
            file_id = seg.data.get("file")
            if file_id:
                return file_id
    return None


def guess_extension(content_type: Optional[str], url: Optional[str]) -> str:
    """根据 content-type 或 url 猜测图片扩展名"""
    if content_type:
        ct = content_type.lower()
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
        if "png" in ct:
            return ".png"
        if "gif" in ct:
            return ".gif"
        if "webp" in ct:
            return ".webp"

    if url:
        url_lower = url.lower()
        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            if url_lower.endswith(ext):
                if ext == ".jpeg":
                    return ".jpg"
                return ext

    return ".jpg"


async def download_image(url: str, save_path: Path) -> tuple[bool, Optional[str]]:
    """异步下载图片到指定路径，返回 (是否成功, 最终路径)"""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            # 猜测扩展名并修正路径
            content_type = resp.headers.get("content-type", "")
            ext = guess_extension(content_type, url)
            if save_path.suffix != ext:
                save_path = save_path.with_suffix(ext)

            save_path.write_bytes(resp.content)
            return True, str(save_path)
    except httpx.HTTPError as e:
        logger.error(f"[custom_welcome] 下载图片失败: {e}")
        return False, None
    except OSError as e:
        logger.error(f"[custom_welcome] 保存图片失败: {e}")
        return False, None


async def _try_get_image_url(bot: Bot, message: Message) -> Optional[str]:
    """尝试从消息中获取图片 URL，包括通过 file 字段调用 bot.get_image"""
    # 1. 优先尝试 URL
    url = extract_image_url(message)
    if url:
        return url

    # 2. 没有 URL 则尝试 file 字段
    file_id = extract_image_file(message)
    if file_id:
        try:
            img_info = await bot.get_image(file=file_id)
            url = img_info.get("url")
            if url:
                return url
        except Exception as e:
            logger.warning(f"[custom_welcome] 通过 file 获取图片信息失败: {e}")

    return None


async def get_image_from_event(bot: Bot, event: GroupMessageEvent) -> Optional[str]:
    """
    从事件中获取图片 URL。
    优先级：当前消息图片 > 引用消息图片
    """
    # 1. 尝试从当前消息提取
    url = await _try_get_image_url(bot, event.message)
    if url:
        return url

    # 2. 尝试从引用消息提取
    reply_seg = None
    for seg in event.message:
        if seg.type == "reply":
            reply_seg = seg
            break

    if reply_seg:
        reply_message_id = reply_seg.data.get("id")
        if reply_message_id:
            try:
                reply_msg = await bot.get_msg(message_id=int(reply_message_id))
                reply_message = Message(reply_msg.get("message", ""))
                url = await _try_get_image_url(bot, reply_message)
                if url:
                    return url
            except Exception as e:
                logger.warning(f"[custom_welcome] 获取引用消息失败: {e}")

    return None


def build_welcome_message(user_id: int, text: Optional[str], image_path: Optional[str]) -> Message:
    """构建欢迎消息：@新人 + 文案 + 图片（如有）"""
    msg = Message()
    msg.append(MessageSegment.at(user_id))
    if text:
        msg.append(MessageSegment.text(f"\n{text}"))
    if image_path:
        path = Path(image_path)
        if path.exists():
            # Windows 兼容：使用 file:/// URI（三斜杠）
            abs_path = path.resolve().as_posix()
            msg.append(MessageSegment.image(f"file:///{abs_path}"))
    return msg
