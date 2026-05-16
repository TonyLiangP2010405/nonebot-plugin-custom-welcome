import asyncio
import random

from nonebot import get_driver, on_command, on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    MessageSegment,
)
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import event_type

from .config import Config
from .data import (
    clear_group_welcome,
    get_group_image_dir,
    get_group_welcome,
    set_group_image,
    set_group_text,
)
from .utils import (
    build_welcome_message,
    check_permission,
    download_image,
    get_image_from_event,
    is_cooldown,
)

# 插件元数据（NoneBot2 官方推荐方式）
__plugin_meta__ = PluginMetadata(
    name="custom_welcome",
    description="自定义加群欢迎插件",
    usage="#设置欢迎文案、#设置欢迎图片、#查看欢迎、#清除欢迎",
)

# 全局配置解析（Pydantic v2 兼容）
global_config = get_driver().config
plugin_config = Config.model_validate(
    {k: getattr(global_config, k) for k in Config.model_fields if hasattr(global_config, k)}
)


# ==================== 事件监听：新人入群 ====================

group_increase = on_notice(rule=event_type("group_increase"), priority=5)


@group_increase.handle()
async def handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    group_id = str(event.group_id)
    user_id = event.user_id

    # 忽略机器人自己入群
    if str(user_id) == str(bot.self_id):
        return

    # 防重复：30秒冷却
    if is_cooldown(group_id, cooldown_seconds=30):
        logger.debug(f"[custom_welcome] 群 {group_id} 处于冷却中，跳过欢迎")
        return

    # 随机延迟 0.5~1 秒，模拟自然响应
    await asyncio.sleep(random.uniform(0.5, 1.0))

    # 获取群配置
    welcome = get_group_welcome(group_id)

    if welcome:
        text = welcome.get("text")
        image_path = welcome.get("image")
        msg = build_welcome_message(user_id, text, image_path)
        await group_increase.send(msg)
    else:
        # 默认欢迎
        msg = MessageSegment.at(user_id) + MessageSegment.text(f"\n{plugin_config.custom_welcome_default_text}")
        await group_increase.send(msg)


# ==================== 命令：设置欢迎文案 ====================

set_text_cmd = on_command("设置欢迎文案", priority=5, block=True)


@set_text_cmd.handle()
async def handle_set_text(bot: Bot, event: GroupMessageEvent, matcher: Matcher, args=CommandArg()):
    # 必须在群聊中使用
    if event.message_type != "group":
        return

    # 权限检查
    if not await check_permission(bot, event):
        await matcher.finish("只有群主或管理员可以设置欢迎消息哦~")

    text = args.extract_plain_text().strip()
    if not text:
        await matcher.finish("请提供欢迎文案，例如：#设置欢迎文案 欢迎加入本群~")

    group_id = str(event.group_id)
    set_group_text(group_id, text)
    await matcher.finish(f"欢迎文案设置成功：\n{text}")


# ==================== 命令：设置欢迎图片 ====================

set_image_cmd = on_command("设置欢迎图片", priority=5, block=True)


@set_image_cmd.handle()
async def handle_set_image(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    # 必须在群聊中使用
    if event.message_type != "group":
        return

    # 权限检查
    if not await check_permission(bot, event):
        await matcher.finish("只有群主或管理员可以设置欢迎消息哦~")

    # 获取图片 URL（支持当前消息 / 引用消息）
    image_url = await get_image_from_event(bot, event)
    if not image_url:
        await matcher.finish("未检测到图片，请发送图片或引用图片后再使用命令。")

    group_id = str(event.group_id)
    image_dir = get_group_image_dir(group_id)

    # 先保存为临时名，下载后再确定扩展名
    temp_path = image_dir / "welcome"
    success, final_path = await download_image(image_url, temp_path)

    if not success:
        await matcher.finish("图片下载失败，请检查图片链接是否有效。")

    set_group_image(group_id, final_path)
    await matcher.finish("欢迎图片设置成功。")


# ==================== 命令：查看欢迎 ====================

view_welcome_cmd = on_command("查看欢迎", priority=5, block=True)


@view_welcome_cmd.handle()
async def handle_view_welcome(event: GroupMessageEvent, matcher: Matcher):
    # 必须在群聊中使用
    if event.message_type != "group":
        return

    group_id = str(event.group_id)
    welcome = get_group_welcome(group_id)

    if not welcome:
        await matcher.finish("该群尚未设置欢迎内容。")

    text = welcome.get("text")
    image_path = welcome.get("image")

    if not text and not image_path:
        await matcher.finish("该群尚未设置欢迎内容。")

    if text:
        await matcher.send(f"当前欢迎文案：\n{text}")

    if image_path:
        from pathlib import Path
        path = Path(image_path)
        if path.exists():
            abs_path = path.resolve().as_posix()
            await matcher.send(MessageSegment.image(f"file:///{abs_path}"))
        else:
            await matcher.send("欢迎图片文件已丢失。")


# ==================== 命令：清除欢迎 ====================

clear_welcome_cmd = on_command("清除欢迎", priority=5, block=True)


@clear_welcome_cmd.handle()
async def handle_clear_welcome(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    # 必须在群聊中使用
    if event.message_type != "group":
        return

    # 权限检查
    if not await check_permission(bot, event):
        await matcher.finish("只有群主或管理员可以设置欢迎消息哦~")

    group_id = str(event.group_id)
    had_config = clear_group_welcome(group_id)

    if not had_config:
        await matcher.finish("该群没有设置欢迎消息。")

    await matcher.finish("已清除当前群的欢迎设置。")
