from sqlmodel import SQLModel, Field
from typing import Optional

class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: str = Field(index=True)      # 产品名称/编号
    title: str                               # 视频标题
    image_url: str                           # 预览图
    category: str = Field(index=True)        # 产品类型 (球服/球鞋)
    finish_time: Optional[str] = None        # 完成时间
    video_type: Optional[str] = None         # 视频类型 (产品展示/促销) -- 新增
    host: str = Field(index=True)            # 主播
    status: str = Field(index=True)          # 当前状态
    platform: Optional[str] = None           # 发布平台
    publish_time: Optional[str] = None       # 发布时间 -- 新增
    remark: Optional[str] = None             # 备注 -- 新增