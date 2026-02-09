import os
import shutil
import math
import uuid
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_
from sqlalchemy import func
from typing import Optional, List

# 确保导入了更新后的模型
from .models import Video
from .processor import process_excel_background

main_app = FastAPI(title="VideoHub Pro")
engine = create_engine("sqlite:///data/inventory.db")

@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    # 生成一张默认图，防止前端 404
    if not os.path.exists("assets/default.png"):
        # 这里你可以放一张真实的默认图，或者让它空着，前端会处理
        pass

main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# --- 核心接口 ---

# 1. 获取动态筛选选项 (新增)
@main_app.get("/api/options")
def get_options():
    with Session(engine) as session:
        # 获取所有去重的主播、状态、分类
        hosts = session.exec(select(Video.host).distinct()).all()
        statuses = session.exec(select(Video.status).distinct()).all()
        categories = session.exec(select(Video.category).distinct()).all()
        
        # 清洗 None 或 空值
        return {
            "hosts": [h for h in hosts if h],
            "statuses": [s for s in statuses if s],
            "categories": [c for c in categories if c]
        }

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
    page: int = 1, size: int = 20,
    keyword: Optional[str] = None,
    host: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None
):
    with Session(engine) as session:
        statement = select(Video)

        if keyword:
            statement = statement.where(or_(
                col(Video.title).contains(keyword),
                col(Video.product_id).contains(keyword),
                col(Video.remark).contains(keyword)
            ))
        
        # 动态筛选逻辑
        if host and host != "全部主播": statement = statement.where(Video.host == host)
        if status and status != "全部状态": statement = statement.where(Video.status == status)
        if category and category != "全部分类": statement = statement.where(Video.category == category)

        count_stmt = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_stmt).one()

        statement = statement.order_by(Video.id.desc()).offset((page - 1) * size).limit(size)
        results = session.exec(statement).all()

        return {
            "items": results, "total": total, "page": page, "size": size, "total_pages": math.ceil(total / size)
        }

@main_app.post("/api/video/save")
async def save_video(
    id: Optional[int] = Form(None),
    product_id: str = Form(...), title: str = Form(...),
    host: str = Form(...), status: str = Form(...),
    category: str = Form(...), video_type: str = Form(""),
    platform: str = Form(""), finish_time: str = Form(""),
    publish_time: str = Form(""), remark: str = Form(""),
    image: UploadFile = None
):
    with Session(engine) as session:
        if id:
            video = session.get(Video, id)
            if not video: raise HTTPException(404, "视频不存在")
        else:
            video = Video(product_id=product_id, title=title, image_url="") # 先给空

        # 赋值
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

        # 图片处理逻辑修复
        if image and image.filename:
            # 确保目录存在
            os.makedirs("assets/previews", exist_ok=True)
            
            # 使用 UUID 防止文件名冲突
            ext = image.filename.split('.')[-1] if '.' in image.filename else "png"
            filename = f"upload_{uuid.uuid4().hex[:8]}.{ext}"
            filepath = os.path.join("assets", "previews", filename)
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
            
            video.image_url = f"/assets/previews/{filename}"
        
        # 如果是新增且没有上传图片，给一个默认空值避免 NoneType 错误
        if not video.image_url:
             video.image_url = "/assets/default.png"

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