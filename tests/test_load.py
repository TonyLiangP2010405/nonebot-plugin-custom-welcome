"""NoneBot 加载测试"""
import nonebot


def test_plugin_load():
    """测试插件能否被 NoneBot 正常加载"""
    nonebot.init()
    plugin = nonebot.get_plugin("nonebot_plugin_custom_welcome")
    if plugin is None:
        plugin = nonebot.load_plugin("nonebot_plugin_custom_welcome")
    assert plugin is not None
    assert plugin.metadata is not None
    assert plugin.metadata.name == "自定义加群欢迎"
