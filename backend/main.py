import os
import shutil
import math
import uuid
import datetime
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, desc, asc, text
from sqlalchemy import func
from typing import Optional

from .processor import process_excel_background
from .models import Video, AppSettings

main_app = FastAPI(title="VideoHub V12.0")
engine = create_engine("sqlite:///data/inventory.db")

@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    # === DB Migration & Repair ===
    with Session(engine) as session:
        try:
            session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except Exception:
            # Add column if missing
            session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
            session.commit()
        
        # Backfill created_at for old records (CRITICAL FIX)
        session.exec(text(f"UPDATE video SET created_at = '{datetime.datetime.now()}' WHERE created_at IS NULL"))
        session.commit()

        # Default Settings
        defaults = {
            "hosts": "小梨,VIVI,七七,杨总",
            "statuses": "待发布,已发布,剪辑中,拍摄中,脚本中",
            "categories": "球服,球鞋,球拍,周边,配件",
            "platforms": "抖音,小红书,视频号,B站",
            "video_types": "产品展示,剧情,口播,Vlog,花絮"
        }
        for k, v in defaults.items():
            if not session.get(AppSettings, k):
                session.add(AppSettings(key=k, value=v))
        session.commit()

main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# === Report API ===
@main_app.get("/api/report")
def get_report(dim: str = "day"):
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        stats = {}
        
        def fmt_date(dt):
            if not dt: return None
            if isinstance(dt, str):
                try: dt = datetime.datetime.strptime(dt[:10], "%Y-%m-%d")
                except: return None
            if dim == 'day': return dt.strftime("%Y-%m-%d")
            if dim == 'week': return dt.strftime("%Y-W%W")
            if dim == 'month': return dt.strftime("%Y-%m")
            return None

        for v in videos:
            # Count Inbound
            d_in = fmt_date(v.created_at)
            if d_in:
                if d_in not in stats: stats[d_in] = {"in": 0, "out": 0}
                stats[d_in]["in"] += 1
            
            # Count Outbound
            if v.status == "已发布" and v.publish_time:
                d_out = fmt_date(v.publish_time)
                if d_out:
                    if d_out not in stats: stats[d_out] = {"in": 0, "out": 0}
                    stats[d_out]["out"] += 1

        keys = sorted(stats.keys())[-15:]
        
        plat_map = {}
        for v in videos:
            if v.status == "已发布" and v.platform:
                for p in v.platform.replace('，', ',').split(','):
                    p = p.strip()
                    if p: plat_map[p] = plat_map.get(p, 0) + 1
        
        return {
            "dates": keys,
            "series_in": [stats[k]["in"] for k in keys],
            "series_out": [stats[k]["out"] for k in keys],
            "platforms": [{"name": k, "value": v} for k, v in plat_map.items()]
        }

# === Options API ===
@main_app.get("/api/options")
def get_options():
    with Session(engine) as session:
        settings = {item.key: item.value.split(',') for item in session.exec(select(AppSettings)).all()}
        def get_merged(col, key):
            db_vals = session.exec(select(col).distinct()).all()
            clean = []
            for item in db_vals:
                if item and str(item).lower() != 'nan': 
                    clean.extend([x.strip() for x in str(item).replace('，', ',').split(',')])
            preset = [x.strip() for x in settings.get(key, []) if x.strip()]
            return sorted(list(set(clean + preset)))
        return {
            "hosts": get_merged(Video.host, "hosts"),
            "categories": get_merged(Video.category, "categories"),
            "statuses": get_merged(Video.status, "statuses"),
            "platforms": get_merged(Video.platform, "platforms"),
            "video_types": get_merged(Video.video_type, "video_types"),
            "product_ids": get_merged(Video.product_id, "ignore")
        }

# === List API ===
@main_app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, sort_by: str = "id", order: str = "desc",
    keyword: Optional[str] = None, host: Optional[str] = None, status: Optional[str] = None,
    category: Optional[str] = None, platform: Optional[str] = None, video_type: Optional[str] = None,
    product_id: Optional[str] = None, title: Optional[str] = None,
    pub_start: Optional[str] = None, pub_end: Optional[str] = None,
    fin_start: Optional[str] = None, fin_end: Optional[str] = None
):
    with Session(engine) as session:
        stmt = select(Video)
        if keyword:
            stmt = stmt.where(or_(col(Video.title).contains(keyword), col(Video.product_id).contains(keyword), col(Video.remark).contains(keyword)))
        if product_id: stmt = stmt.where(col(Video.product_id).contains(product_id))
        if title: stmt = stmt.where(col(Video.title).contains(title))
        if host and host!="全部": stmt = stmt.where(col(Video.host).contains(host))
        if platform and platform!="全部": stmt = stmt.where(col(Video.platform).contains(platform))
        if category and category!="全部": stmt = stmt.where(Video.category==category)
        if status and status!="全部": stmt = stmt.where(Video.status==status)
        if video_type and video_type!="全部": stmt = stmt.where(Video.video_type==video_type)
        if pub_start: stmt = stmt.where(Video.publish_time >= pub_start)
        if pub_end: stmt = stmt.where(Video.publish_time <= pub_end)
        if fin_start: stmt = stmt.where(Video.finish_time >= fin_start)
        if fin_end: stmt = stmt.where(Video.finish_time <= fin_end)

        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        sort_col = getattr(Video, sort_by, Video.id)
        stmt = stmt.order_by(asc(sort_col) if order=="asc" else desc(sort_col)).offset((page-1)*size).limit(size)
        return {"items": session.exec(stmt).all(), "total": total, "page": page, "size": size, "total_pages": math.ceil(total/size)}

# === Actions ===
@main_app.post("/api/upload")
async def upload_image(file: UploadFile):
    os.makedirs("assets/previews", exist_ok=True)
    ext = file.filename.split('.')[-1] if '.' in file.filename else "png"
    filename = f"upl_{uuid.uuid4().hex[:8]}.{ext}"
    with open(f"assets/previews/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return {"url": f"/assets/previews/{filename}"}

@main_app.post("/api/video/save")
async def save_video(
    id: Optional[str] = Form(None), 
    product_id: Optional[str] = Form(None), title: Optional[str] = Form(None),
    host: Optional[str] = Form(None), status: Optional[str] = Form(None),
    category: Optional[str] = Form(None), video_type: Optional[str] = Form(None),
    platform: Optional[str] = Form(None), finish_time: Optional[str] = Form(None),
    publish_time: Optional[str] = Form(None), remark: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None)
):
    with Session(engine) as session:
        if not id or id in ['new', 'temp', 'undefined', 'null']:
            video = Video(
                product_id=product_id or "未命名", 
                title=title or "新建", 
                image_url="/assets/default.png",
                created_at=datetime.datetime.now()
            )
            session.add(video)
        else:
            video = session.get(Video, int(id))
            if not video: raise HTTPException(404, "Not found")
        
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
            
        session.commit()
        return {"message": "Saved"}

@main_app.delete("/api/video/{video_id}")
def delete_video(video_id: int):
    with Session(engine) as session:
        session.delete(session.get(Video, video_id))
        session.commit()
    return {"message": "Deleted"}

@main_app.get("/api/stats")
def get_stats_basic():
    with Session(engine) as session:
        total = session.exec(select(func.count(Video.id))).one()
        pending = session.exec(select(func.count(Video.id)).where(Video.status == "待发布")).one()
        return {"total": total, "pending": pending}

@main_app.post("/api/settings")
def update_settings(key: str = Form(...), value: str = Form(...)):
    with Session(engine) as session:
        s = session.get(AppSettings, key)
        if not s: s = AppSettings(key=key, value=value)
        else: s.value = value
        session.add(s)
        session.commit()
    return {"message": "ok"}

@main_app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    if not os.path.exists("temp_uploads"): raise HTTPException(404)
    files = [f for f in os.listdir("temp_uploads") if f.endswith(".xlsx")]
    if not files: raise HTTPException(404)
    bg_tasks.add_task(process_excel_background, os.path.join("temp_uploads", files[0]), engine)
    return {"message": "Starting..."}