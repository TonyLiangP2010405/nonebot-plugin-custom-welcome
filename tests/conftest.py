import os

# 通过环境变量设置命令前缀，确保 NoneBot2 能正确读取
os.environ["COMMAND_START"] = '["#", "/"]'

import nonebot
from nonebug import App

# 初始化 NoneBot
nonebot.init()

# 模块级别加载插件，确保测试文件顶层导入时插件已注册
nonebot.load_plugin("nonebot_plugin_custom_welcome")
