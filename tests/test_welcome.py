import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from nonebot.adapters.onebot.v11 import (
    Adapter,
    Bot,
    Message,
    MessageSegment,
)
from nonebot.adapters.onebot.v11.event import (
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    Sender,
)
from nonebug import App

from nonebot_plugin_custom_welcome import (
    clear_welcome_cmd,
    group_increase,
    set_image_cmd,
    set_text_cmd,
    view_welcome_cmd,
)
from nonebot_plugin_custom_welcome.data import (
    clear_group_welcome,
    get_group_welcome,
    load_config,
    save_config,
    set_group_image,
    set_group_text,
)
from nonebot_plugin_custom_welcome.utils import (
    build_welcome_message,
    check_permission,
    guess_extension,
    is_cooldown,
)


# ==================== data.py 测试 ====================

class TestDataStorage:
    """测试数据存储层"""

    def test_load_save_config(self, tmp_path):
        """测试配置读写"""
        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            config = {"123456": {"text": "欢迎", "image": "/path/to/img.jpg"}}
            save_config(config)
            loaded = load_config()
            assert loaded == config

    def test_set_group_text(self, tmp_path):
        """测试设置群文案"""
        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            set_group_text("123456", "测试文案")
            welcome = get_group_welcome("123456")
            assert welcome["text"] == "测试文案"

    def test_clear_group_welcome(self, tmp_path):
        """测试清除群配置并删除图片"""
        img_path = tmp_path / "test.jpg"
        img_path.write_text("fake image")
        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            set_group_text("123456", "测试")
            set_group_image("123456", str(img_path))
            assert img_path.exists()
            result = clear_group_welcome("123456")
            assert result is True
            assert not img_path.exists()
            assert get_group_welcome("123456") is None

    def test_multi_group_isolation(self, tmp_path):
        """测试多群配置互不影响"""
        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            set_group_text("111", "群1文案")
            set_group_text("222", "群2文案")
            assert get_group_welcome("111")["text"] == "群1文案"
            assert get_group_welcome("222")["text"] == "群2文案"
            clear_group_welcome("111")
            assert get_group_welcome("111") is None
            assert get_group_welcome("222") is not None


# ==================== utils.py 测试 ====================

class TestUtils:
    """测试工具函数"""

    def test_guess_extension(self):
        assert guess_extension("image/jpeg", None) == ".jpg"
        assert guess_extension("image/png", None) == ".png"
        assert guess_extension(None, "http://a.com/b.gif") == ".gif"
        assert guess_extension(None, "http://a.com/b.webp") == ".webp"
        assert guess_extension(None, None) == ".jpg"

    def test_is_cooldown(self):
        """测试冷却机制"""
        assert is_cooldown("123", 30) is False  # 第一次触发
        assert is_cooldown("123", 30) is True   # 冷却中
        assert is_cooldown("456", 30) is False  # 不同群不影响

    def test_build_welcome_message(self, tmp_path):
        """测试欢迎消息构建"""
        img = tmp_path / "test.jpg"
        img.write_text("fake")
        msg = build_welcome_message(12345, "欢迎", str(img))
        assert any(seg.type == "at" and seg.data.get("qq") == "12345" for seg in msg)
        assert any(seg.type == "text" and "欢迎" in seg.data.get("text", "") for seg in msg)
        assert any(seg.type == "image" for seg in msg)

    @pytest.mark.asyncio
    async def test_check_permission_owner(self):
        """测试群主有权限"""
        bot = AsyncMock()
        event = AsyncMock()
        event.sender = Sender(role="owner", user_id=100)
        assert await check_permission(bot, event) is True

    @pytest.mark.asyncio
    async def test_check_permission_member(self):
        """测试普通成员无权限"""
        bot = AsyncMock()
        event = AsyncMock()
        event.sender = Sender(role="member", user_id=100)
        # SUPERUSER 是 Permission 对象，patch 为 AsyncMock
        with patch("nonebot_plugin_custom_welcome.utils.SUPERUSER", new=AsyncMock(return_value=False)):
            assert await check_permission(bot, event) is False


# ==================== __init__.py matcher 测试 ====================

class TestMatchers:
    """使用 NoneBug 测试 matcher"""

    @pytest.mark.asyncio
    async def test_default_welcome(self, app: App):
        """测试新人入群默认欢迎"""
        async with app.test_matcher(group_increase) as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
            event = GroupIncreaseNoticeEvent(
                time=int(time.time()),
                self_id=1,
                post_type="notice",
                notice_type="group_increase",
                sub_type="approve",
                user_id=12345,
                group_id=10086,
                operator_id=0,
            )
            ctx.receive_event(bot, event)
            ctx.should_call_send(
                event,
                Message(MessageSegment.at(12345) + MessageSegment.text("\n欢迎新人~！")),
                result=None,
                bot=bot,
            )

    @pytest.mark.asyncio
    async def test_self_join_no_welcome(self, app: App):
        """测试机器人自己入群不触发欢迎"""
        async with app.test_matcher(group_increase) as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
            event = GroupIncreaseNoticeEvent(
                time=int(time.time()),
                self_id=1,
                post_type="notice",
                notice_type="group_increase",
                sub_type="approve",
                user_id=1,  # 机器人自己
                group_id=10086,
                operator_id=0,
            )
            ctx.receive_event(bot, event)
            # 不应该发送任何消息

    @pytest.mark.asyncio
    async def test_set_welcome_text_command(self, app: App, tmp_path):
        """测试设置欢迎文案命令"""
        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            async with app.test_matcher(set_text_cmd) as ctx:
                adapter = ctx.create_adapter(base=Adapter)
                bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
                event = GroupMessageEvent(
                    time=int(time.time()),
                    self_id=1,
                    post_type="message",
                    sub_type="normal",
                    user_id=100,
                    message_type="group",
                    message_id=1,
                    message=Message("#设置欢迎文案 欢迎加入本群~"),
                    original_message=Message("#设置欢迎文案 欢迎加入本群~"),
                    raw_message="#设置欢迎文案 欢迎加入本群~",
                    font=0,
                    sender=Sender(role="owner", user_id=100),
                    group_id=10086,
                )
                ctx.receive_event(bot, event)
                ctx.should_call_send(
                    event,
                    "欢迎文案设置成功：\n欢迎加入本群~",
                    result=None,
                    bot=bot,
                )
                ctx.should_finished(set_text_cmd)

            # 验证数据层
            welcome = get_group_welcome("10086")
            assert welcome is not None
            assert welcome["text"] == "欢迎加入本群~"

    @pytest.mark.asyncio
    async def test_set_welcome_text_no_permission(self, app: App, tmp_path):
        """测试普通成员无法设置欢迎文案"""
        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            async with app.test_matcher(set_text_cmd) as ctx:
                adapter = ctx.create_adapter(base=Adapter)
                bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
                event = GroupMessageEvent(
                    time=int(time.time()),
                    self_id=1,
                    post_type="message",
                    sub_type="normal",
                    user_id=101,
                    message_type="group",
                    message_id=2,
                    message=Message("#设置欢迎文案 测试"),
                    original_message=Message("#设置欢迎文案 测试"),
                    raw_message="#设置欢迎文案 测试",
                    font=0,
                    sender=Sender(role="member", user_id=101),
                    group_id=10086,
                )
                ctx.receive_event(bot, event)
                ctx.should_call_send(
                    event,
                    "只有群主或管理员可以设置欢迎消息哦~",
                    result=None,
                    bot=bot,
                )
                ctx.should_finished(set_text_cmd)

            # 验证数据未被修改
            assert get_group_welcome("10086") is None

    @pytest.mark.asyncio
    async def test_view_welcome_empty(self, app: App, tmp_path):
        """测试查看空配置"""
        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            async with app.test_matcher(view_welcome_cmd) as ctx:
                adapter = ctx.create_adapter(base=Adapter)
                bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
                event = GroupMessageEvent(
                    time=int(time.time()),
                    self_id=1,
                    post_type="message",
                    sub_type="normal",
                    user_id=100,
                    message_type="group",
                    message_id=3,
                    message=Message("#查看欢迎"),
                    original_message=Message("#查看欢迎"),
                    raw_message="#查看欢迎",
                    font=0,
                    sender=Sender(role="member", user_id=100),
                    group_id=10086,
                )
                ctx.receive_event(bot, event)
                ctx.should_call_send(
                    event,
                    "该群尚未设置欢迎内容。",
                    result=None,
                    bot=bot,
                )
                ctx.should_finished(view_welcome_cmd)

    @pytest.mark.asyncio
    async def test_clear_welcome_command(self, app: App, tmp_path):
        """测试清除欢迎命令"""
        img_path = tmp_path / "10086" / "welcome.jpg"
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_text("fake")

        with patch("nonebot.matcher.Matcher.finish", new_callable=AsyncMock) as mock_finish:
            with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
                # 先设置配置
                set_group_text("10086", "测试文案")
                set_group_image("10086", str(img_path))

                async with app.test_matcher(clear_welcome_cmd) as ctx:
                    adapter = ctx.create_adapter(base=Adapter)
                    bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
                    event = GroupMessageEvent(
                        time=int(time.time()),
                        self_id=1,
                        post_type="message",
                        sub_type="normal",
                        user_id=100,
                        message_type="group",
                        message_id=4,
                        message=Message("#清除欢迎"),
                        original_message=Message("#清除欢迎"),
                        raw_message="#清除欢迎",
                        font=0,
                        sender=Sender(role="owner", user_id=100),
                        group_id=10086,
                    )
                    ctx.receive_event(bot, event)

                # 验证 finish 被调用
                mock_finish.assert_called_once()
                assert "已清除" in str(mock_finish.call_args[0][0])

            # 验证图片文件被删除
            assert not img_path.exists()
            assert get_group_welcome("10086") is None

    @pytest.mark.asyncio
    async def test_set_welcome_image_command(self, app: App, tmp_path):
        """测试设置欢迎图片命令（从消息图片提取）"""
        img_dir = tmp_path / "images" / "10086"
        img_dir.mkdir(parents=True, exist_ok=True)

        with patch("nonebot_plugin_custom_welcome.data.CONFIG_FILE", tmp_path / "welcome.json"):
            with patch("nonebot_plugin_custom_welcome.data.IMAGE_DIR", tmp_path / "images"):
                with patch("nonebot_plugin_custom_welcome.utils.httpx.AsyncClient") as mock_client:
                    mock_resp = AsyncMock()
                    mock_resp.headers = {"content-type": "image/jpeg"}
                    mock_resp.content = b"fake_image_data"
                    mock_resp.raise_for_status = AsyncMock()
                    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
                    mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
                    mock_client.return_value.get = AsyncMock(return_value=mock_resp)

                    async with app.test_matcher(set_image_cmd) as ctx:
                        adapter = ctx.create_adapter(base=Adapter)
                        bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
                        event = GroupMessageEvent(
                            time=int(time.time()),
                            self_id=1,
                            post_type="message",
                            sub_type="normal",
                            user_id=100,
                            message_type="group",
                            message_id=5,
                            message=Message([
                                MessageSegment.text("#设置欢迎图片 "),
                                MessageSegment.image("http://example.com/test.jpg"),
                            ]),
                            original_message=Message([
                                MessageSegment.text("#设置欢迎图片 "),
                                MessageSegment.image("http://example.com/test.jpg"),
                            ]),
                            raw_message="#设置欢迎图片 [CQ:image,file=test.jpg,url=http://example.com/test.jpg]",
                            font=0,
                            sender=Sender(role="owner", user_id=100),
                            group_id=10086,
                        )
                        ctx.receive_event(bot, event)
                        ctx.should_call_send(
                            event,
                            "欢迎图片设置成功。",
                            result=None,
                            bot=bot,
                        )
                        ctx.should_finished(set_image_cmd)

                    # 验证图片已保存
                    welcome = get_group_welcome("10086")
                    assert welcome is not None
                    assert "image" in welcome
                    assert Path(welcome["image"]).exists()
