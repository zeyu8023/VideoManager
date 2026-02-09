import os
import shutil
import math
import uuid
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, desc, asc
from sqlalchemy import func
from typing import Optional

from .processor import process_excel_background
from .models import Video, AppSettings

main_app = FastAPI(title="VideoHub V6.0")
engine = create_engine("sqlite:///data/inventory.db")

@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    # 默认配置 (兜底用)
    with Session(engine) as session:
        if not session.get(AppSettings, "hosts"):
            session.add(AppSettings(key="hosts", value="小梨,VIVI,七七"))
        if not session.get(AppSettings, "statuses"):
            session.add(AppSettings(key="statuses", value="待发布,已发布,剪辑中"))
        if not session.get(AppSettings, "categories"):
            session.add(AppSettings(key="categories", value="球服,球鞋,球拍"))
        if not session.get(AppSettings, "platforms"):
            session.add(AppSettings(key="platforms", value="抖音,小红书"))
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

# === 核心选项接口 (修复：强力读取数据库) ===
@main_app.get("/api/options")
def get_options():
    with Session(engine) as session:
        # 获取配置
        settings = {item.key: item.value.split(',') for item in session.exec(select(AppSettings)).all()}
        
        # 辅助函数：合并 数据库distinct值 + 全局配置值
        def get_vals(field, key):
            # 1. 查库
            db_res = session.exec(select(field).distinct()).all()
            # 2. 清洗
            clean_db = []
            for item in db_res:
                if item and str(item) != 'nan':
                    # 支持逗号分隔 (多选兼容)
                    clean_db.extend([x.strip() for x in str(item).split(',')])
            
            # 3. 合并配置
            preset = [x.strip() for x in settings.get(key, []) if x.strip()]
            
            # 4. 去重排序
            return sorted(list(set(clean_db + preset)))

        return {
            "hosts": get_vals(Video.host, "hosts"),
            "categories": get_vals(Video.category, "categories"),
            "statuses": get_vals(Video.status, "statuses"),
            "platforms": get_vals(Video.platform, "platforms"),
            "video_types": get_vals(Video.video_type, "video_types"),
            # 新增：返回所有产品编号供前端联想
            "product_ids": get_vals(Video.product_id, "ignore_config") 
        }

# === 列表查询 ===
@main_app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, 
    sort_by: Optional[str] = "id", order: Optional[str] = "desc",
    keyword: Optional[str] = None, # 全局搜索
    
    # 精确筛选
    product_id: Optional[str] = None,
    title: Optional[str] = None,
    host: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    platform: Optional[str] = None,
    video_type: Optional[str] = None,
    remark: Optional[str] = None,
    
    # 时间
    pub_start: Optional[str] = None, pub_end: Optional[str] = None,
    fin_start: Optional[str] = None, fin_end: Optional[str] = None
):
    with Session(engine) as session:
        statement = select(Video)
        
        # 1. 全局搜索 (搜索框)
        if keyword:
            statement = statement.where(or_(
                col(Video.title).contains(keyword),
                col(Video.product_id).contains(keyword),
                col(Video.remark).contains(keyword)
            ))
        
        # 2. 侧边栏筛选
        if product_id: statement = statement.where(col(Video.product_id).contains(product_id))
        if title: statement = statement.where(col(Video.title).contains(title))
        if remark: statement = statement.where(col(Video.remark).contains(remark))
        
        # 下拉框 (支持多选模糊查)
        if host and host != "全部": statement = statement.where(col(Video.host).contains(host))
        if platform and platform != "全部": statement = statement.where(col(Video.platform).contains(platform))
        if category and category != "全部": statement = statement.where(Video.category == category)
        if status and status != "全部": statement = statement.where(Video.status == status)
        if video_type and video_type != "全部": statement = statement.where(Video.video_type == video_type)
        
        # 时间
        if pub_start: statement = statement.where(Video.publish_time >= pub_start)
        if pub_end: statement = statement.where(Video.publish_time <= pub_end)
        if fin_start: statement = statement.where(Video.finish_time >= fin_start)
        if fin_end: statement = statement.where(Video.finish_time <= fin_end)

        # 统计 & 排序
        total = session.exec(select(func.count()).select_from(statement.subquery())).one()
        
        sort_col = getattr(Video, sort_by, Video.id)
        statement = statement.order_by(asc(sort_col) if order == "asc" else desc(sort_col))
        
        results = session.exec(statement.offset((page - 1) * size).limit(size)).all()

        return {"items": results, "total": total, "page": page, "size": size, "total_pages": math.ceil(total / size)}

# === 保存/上传/删除 (保持稳定) ===
@main_app.post("/api/upload")
async def upload_image(file: UploadFile):
    os.makedirs("assets/previews", exist_ok=True)
    ext = file.filename.split('.')[-1] if '.' in file.filename else "png"
    filename = f"drag_{uuid.uuid4().hex[:8]}.{ext}"
    with open(f"assets/previews/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return {"url": f"/assets/previews/{filename}"}

@main_app.post("/api/video/save")
async def save_video(
    id: Optional[int] = Form(None),
    product_id: Optional[str] = Form(None), title: Optional[str] = Form(None),
    host: Optional[str] = Form(None), status: Optional[str] = Form(None),
    category: Optional[str] = Form(None), video_type: Optional[str] = Form(None),
    platform: Optional[str] = Form(None), finish_time: Optional[str] = Form(None),
    publish_time: Optional[str] = Form(None), remark: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None)
):
    with Session(engine) as session:
        if id:
            video = session.get(Video, id)
            if not video: raise HTTPException(404, "Not found")
        else:
            video = Video(product_id=product_id or "New", title=title or "未命名", image_url="/assets/default.png")

        if product_id is not None: video.product_id = product_id
        if title is not None: video.title = title
        if host is not None: video.host = host
        if status is not None: video.status = status
        if category is not None: video.category = category
        if video_type is not None: video.video_type = video_type
        if platform is not None: video.platform = platform
        if finish_time is not None: video.finish_time = finish_time
        if publish_time is not None: video.publish_time = publish_time
        if remark is not None: video.remark = remark
        if image_url and "nan" not in image_url: video.image_url = image_url
            
        session.add(video)
        session.commit()
        return {"message": "Saved"}

@main_app.delete("/api/video/{video_id}")
def delete_video(video_id: int):
    with Session(engine) as session:
        session.delete(session.get(Video, video_id))
        session.commit()
    return {"message": "Deleted"}

@main_app.get("/api/stats")
def get_stats():
    with Session(engine) as session:
        total = session.exec(select(func.count(Video.id))).one()
        pending = session.exec(select(func.count(Video.id)).where(Video.status == "待发布")).one()
        return {"total": total, "pending": pending, "host": "VIVI"}

@main_app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    if not os.path.exists("temp_uploads"): raise HTTPException(404, "Dir not found")
    files = [f for f in os.listdir("temp_uploads") if f.endswith(".xlsx")]
    if not files: raise HTTPException(404, "No xlsx found")
    bg_tasks.add_task(process_excel_background, os.path.join("temp_uploads", files[0]), engine)
    return {"message": "Starting..."}