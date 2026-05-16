from pydantic import BaseModel


class Config(BaseModel):
    """插件配置类"""

    # 默认欢迎文案
    custom_welcome_default_text: str = "欢迎新人~！"
    # 数据存储目录
    custom_welcome_data_dir: str = "data/custom_welcome"
