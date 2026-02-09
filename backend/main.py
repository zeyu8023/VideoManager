import os
import shutil
import math
import uuid
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, Field
from sqlalchemy import func
from typing import Optional, List

# 导入 processor
from .processor import process_excel_background
# 导入 models (确保 models.py 存在且正确)
from .models import Video, AppSettings

main_app = FastAPI(title="VideoHub Ultimate")
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

# === 核心选项接口 (混合模式) ===
@main_app.get("/api/options")
def get_options():
    with Session(engine) as session:
        # 获取数据库中已有的去重数据
        db_hosts = session.exec(select(Video.host).distinct()).all()
        db_cats = session.exec(select(Video.category).distinct()).all()
        db_stats = session.exec(select(Video.status).distinct()).all()
        db_plats = session.exec(select(Video.platform).distinct()).all()
        
        # 获取设置里的预设数据
        settings = {item.key: item.value.split(',') for item in session.exec(select(AppSettings)).all()}
        
        # 合并去重
        def merge(db_list, key):
            preset = settings.get(key, [])
            # 过滤掉 None 和空字符串
            valid_db = [x for x in db_list if x]
            return list(set(preset + valid_db))

        return {
            "hosts": sorted(merge(db_hosts, "hosts")),
            "categories": sorted(merge(db_cats, "categories")),
            "statuses": sorted(merge(db_stats, "statuses")),
            "platforms": sorted(merge(db_plats, "platforms"))
        }

# === 图片上传 ===
@main_app.post("/api/upload")
async def upload_image(file: UploadFile):
    os.makedirs("assets/previews", exist_ok=True)
    ext = file.filename.split('.')[-1] if '.' in file.filename else "png"
    filename = f"drag_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join("assets", "previews", filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"/assets/previews/{filename}"}

# === 统计接口 ===
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

# === 列表接口 (含时间筛选) ===
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
        
        # 时间筛选
        if pub_start: statement = statement.where(Video.publish_time >= pub_start)
        if pub_end: statement = statement.where(Video.publish_time <= pub_end)

        count_stmt = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_stmt).one()

        statement = statement.order_by(Video.id.desc()).offset((page - 1) * size).limit(size)
        results = session.exec(statement).all()

        return {"items": results, "total": total, "page": page, "size": size, "total_pages": math.ceil(total / size)}

# === 保存接口 ===
@main_app.post("/api/video/save")
async def save_video(
    id: Optional[int] = Form(None),
    product_id: Optional[str] = Form(None), 
    title: Optional[str] = Form(None),
    host: Optional[str] = Form(None), 
    status: Optional[str] = Form(None),
    category: Optional[str] = Form(None), 
    video_type: Optional[str] = Form(None),
    platform: Optional[str] = Form(None), 
    finish_time: Optional[str] = Form(None),
    publish_time: Optional[str] = Form(None), 
    remark: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None)
):
    with Session(engine) as session:
        if id:
            video = session.get(Video, id)
            if not video: raise HTTPException(404, "视频不存在")
        else:
            video = Video(
                product_id=product_id or "未命名", 
                title=title or "新视频", 
                image_url="/assets/default.png"
            )

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
        
        if image_url and image_url not in ["nan", "undefined", "null"]: 
            video.image_url = image_url
            
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