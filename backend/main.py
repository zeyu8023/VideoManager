import os
import shutil
import math
import uuid
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, Field
from sqlalchemy import func
from typing import Optional, List

from .models import Video
from .processor import process_excel_background

# === 新增：全局配置模型 ===
class AppSettings(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str # 用逗号分隔的字符串存储，例如 "小梨,VIVI,七七"

main_app = FastAPI(title="VideoHub Pro Max")
engine = create_engine("sqlite:///data/inventory.db")

@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    # 初始化默认配置
    with Session(engine) as session:
        if not session.get(AppSettings, "hosts"):
            session.add(AppSettings(key="hosts", value="小梨,VIVI,七七,杨总"))
        if not session.get(AppSettings, "statuses"):
            session.add(AppSettings(key="statuses", value="待发布,已发布,剪辑中,拍摄中"))
        if not session.get(AppSettings, "categories"):
            session.add(AppSettings(key="categories", value="球服,球鞋,球拍,周边"))
        if not session.get(AppSettings, "platforms"):
            session.add(AppSettings(key="platforms", value="抖音,小红书,视频号"))
        session.commit()

main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# === 配置接口 ===
@main_app.get("/api/settings")
def get_settings():
    with Session(engine) as session:
        return {item.key: item.value.split(',') for item in session.exec(select(AppSettings)).all()}

@main_app.post("/api/settings")
def update_settings(key: str = Form(...), value: str = Form(...)):
    with Session(engine) as session:
        setting = session.get(AppSettings, key)
        if not setting:
            setting = AppSettings(key=key, value=value)
        else:
            setting.value = value
        session.add(setting)
        session.commit()
    return {"message": "配置已更新"}

# === 图片上传接口 (支持拖拽/粘贴) ===
@main_app.post("/api/upload")
async def upload_image(file: UploadFile):
    os.makedirs("assets/previews", exist_ok=True)
    ext = file.filename.split('.')[-1] if '.' in file.filename else "png"
    filename = f"drag_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join("assets", "previews", filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {"url": f"/assets/previews/{filename}"}

# === 现有接口 (保持不变) ===
@main_app.get("/api/stats")
def get_stats():
    with Session(engine) as session:
        total = session.exec(select(func.count(Video.id))).one()
        pending = session.exec(select(func.count(Video.id)).where(Video.status == "待发布")).one()
        try:
            top_host = session.exec(select(Video.host, func.count(Video.host)).group_by(Video.host).order_by(func.count(Video.host).desc()).limit(1)).first()
            host_name = top_host[0] if top_host else "暂无"
        except:
            host_name = "暂无"
        return {"total": total, "pending": pending, "host": host_name}

@main_app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, 
    keyword: Optional[str] = None, host: Optional[str] = None,
    status: Optional[str] = None, category: Optional[str] = None,
    pub_start: Optional[str] = None, pub_end: Optional[str] = None
):
    with Session(engine) as session:
        statement = select(Video)
        if keyword:
            statement = statement.where(or_(
                col(Video.title).contains(keyword),
                col(Video.product_id).contains(keyword),
                col(Video.remark).contains(keyword)
            ))
        if host and host != "全部主播": statement = statement.where(Video.host == host)
        if status and status != "全部状态": statement = statement.where(Video.status == status)
        if category and category != "全部分类": statement = statement.where(Video.category == category)
        if pub_start: statement = statement.where(Video.publish_time >= pub_start)
        if pub_end: statement = statement.where(Video.publish_time <= pub_end)

        count_stmt = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_stmt).one()

        statement = statement.order_by(Video.id.desc()).offset((page - 1) * size).limit(size)
        results = session.exec(statement).all()

        return {"items": results, "total": total, "page": page, "size": size, "total_pages": math.ceil(total / size)}

@main_app.post("/api/video/save")
async def save_video(
    id: Optional[int] = Form(None),
    product_id: str = Form(...), title: str = Form(...),
    host: str = Form(...), status: str = Form(...),
    category: str = Form(...), video_type: str = Form(""),
    platform: str = Form(""), finish_time: str = Form(""),
    publish_time: str = Form(""), remark: str = Form(""),
    image_url: str = Form("") # 改动：直接接收 URL，或者上面的 file
):
    with Session(engine) as session:
        if id:
            video = session.get(Video, id)
            if not video: raise HTTPException(404, "视频不存在")
        else:
            video = Video(product_id=product_id, title=title, image_url="/assets/default.png")

        video.product_id = product_id
        video.title = title
        video.host = host
        video.status = status
        video.category = category
        video.video_type = video_type
        video.platform = platform
        video.finish_time = finish_time
        video.publish_time = publish_time
        video.remark = remark
        if image_url: video.image_url = image_url # 更新图片
        
        session.add(video)
        session.commit()
        return {"message": "保存成功"}

@main_app.delete("/api/video/{video_id}")
def delete_video(video_id: int):
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video: raise HTTPException(404, "未找到")
        session.delete(video)
        session.commit()
    return {"message": "已删除"}

@main_app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    if not os.path.exists("temp_uploads"): raise HTTPException(404, "目录不存在")
    files = [f for f in os.listdir("temp_uploads") if f.endswith(".xlsx")]
    if not files: raise HTTPException(404, "无文件")
    bg_tasks.add_task(process_excel_background, os.path.join("temp_uploads", files[0]), engine)
    return {"message": "后台处理中..."}