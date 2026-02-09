from sqlmodel import SQLModel, Field
from typing import Optional

# 这是唯一的 Video 表定义
class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: str = Field(index=True)
    title: str
    image_url: str
    category: Optional[str] = None
    finish_time: Optional[str] = None
    video_type: Optional[str] = None
    host: Optional[str] = Field(default=None, index=True)
    status: Optional[str] = Field(default=None, index=True)
    platform: Optional[str] = None
    publish_time: Optional[str] = None
    remark: Optional[str] = None

# 全局配置表
class AppSettings(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str