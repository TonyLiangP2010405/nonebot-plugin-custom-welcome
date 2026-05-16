import json
import os
import time
from pathlib import Path
from typing import Dict, Optional

from nonebot import get_driver
from nonebot.log import logger

from .config import Config

# 安全地从全局配置中提取插件需要的字段（Pydantic v2 兼容）
global_config = get_driver().config
plugin_config = Config.model_validate(
    {k: getattr(global_config, k) for k in Config.model_fields if hasattr(global_config, k)}
)

# 数据目录（在 NoneBot 启动时基于当前工作目录解析为绝对路径）
DATA_DIR = Path(plugin_config.custom_welcome_data_dir).resolve()
CONFIG_FILE = DATA_DIR / "welcome.json"
IMAGE_DIR = DATA_DIR / "images"


def ensure_data_dir():
    """确保数据目录和图片目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, dict]:
    """加载欢迎配置，文件不存在时自动返回空字典"""
    ensure_data_dir()
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"[custom_welcome] 加载配置文件失败: {e}")
        return {}


def save_config(config: Dict[str, dict]):
    """保存欢迎配置，使用临时文件 + rename 的原子写入，避免写坏"""
    ensure_data_dir()
    try:
        temp_path = DATA_DIR / f"welcome_tmp_{os.getpid()}_{int(time.time() * 1000)}.json"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, CONFIG_FILE)
    except OSError as e:
        logger.error(f"[custom_welcome] 保存配置文件失败: {e}")
        raise


def get_group_welcome(group_id: str) -> Optional[dict]:
    """获取指定群的欢迎配置"""
    config = load_config()
    return config.get(str(group_id))


def set_group_text(group_id: str, text: str):
    """设置指定群的欢迎文案"""
    config = load_config()
    group_id = str(group_id)
    if group_id not in config:
        config[group_id] = {}
    config[group_id]["text"] = text
    save_config(config)


def set_group_image(group_id: str, image_path: str):
    """设置指定群的欢迎图片，自动删除旧图片"""
    config = load_config()
    group_id = str(group_id)
    if group_id not in config:
        config[group_id] = {}
    # 删除旧图片
    old_image = config[group_id].get("image")
    if old_image:
        old_path = Path(old_image)
        if old_path.exists():
            try:
                old_path.unlink()
            except OSError as e:
                logger.warning(f"[custom_welcome] 删除旧图片失败: {e}")
    config[group_id]["image"] = image_path
    save_config(config)


def clear_group_welcome(group_id: str) -> bool:
    """清除指定群的欢迎配置，同时删除本地图片文件，返回是否清除了内容"""
    config = load_config()
    group_id = str(group_id)
    if group_id not in config:
        return False

    # 删除图片文件
    image_path = config[group_id].get("image")
    if image_path:
        path = Path(image_path)
        if path.exists():
            try:
                path.unlink()
            except OSError as e:
                logger.warning(f"[custom_welcome] 删除图片失败: {e}")

    # 删除群配置
    del config[group_id]
    save_config(config)
    return True


def get_group_image_dir(group_id: str) -> Path:
    """获取指定群的图片目录"""
    dir_path = IMAGE_DIR / str(group_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path
