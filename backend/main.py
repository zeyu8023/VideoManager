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
from typing import Optional, List

from .processor import process_excel_background
from .models import Video, AppSettings

main_app = FastAPI(title="VideoHub V10.0")
engine = create_engine("sqlite:///data/inventory.db")

@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    # === 智能数据库迁移 (防止旧版DB报错) ===
    with Session(engine) as session:
        try:
            # 尝试查询 created_at，如果报错说明是旧表
            session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except Exception:
            print("正在升级数据库结构...")
            # 手动添加列 (SQLite ALTER TABLE)
            session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
            session.commit()

    # 初始化配置
    with Session(engine) as session:
        defaults = {
            "hosts": "小梨,VIVI,七七,杨总",
            "statuses": "待发布,已发布,剪辑中,拍摄中",
            "categories": "球服,球鞋,球拍,周边",
            "platforms": "抖音,小红书,视频号",
            "video_types": "产品展示,剧情,口播,Vlog"
        }
        for k, v in defaults.items():
            if not session.get(AppSettings, k):
                session.add(AppSettings(key=k, value=v))
        session.commit()

main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# === 统计报表接口 (新) ===
@main_app.get("/api/report")
def get_report(dim: str = "day"): # dim: day, week, month
    with Session(engine) as session:
        # 1. 平台分布 (饼图)
        plat_data = []
        plats = session.exec(select(Video.platform).where(Video.status == "已发布")).all()
        # 简单的Python计数 (处理逗号分隔)
        p_counts = {}
        for p_str in plats:
            if p_str:
                for p in p_str.split(','): # 处理多选
                    p = p.strip()
                    if p: p_counts[p] = p_counts.get(p, 0) + 1
        plat_data = [{"name": k, "value": v} for k, v in p_counts.items()]

        # 2. 趋势图 (入库 vs 发布)
        # 简化逻辑：按日期聚合。真实环境可能需要更复杂的SQL Group By
        # 这里为了兼容性，取回数据在内存处理 (适用于 <10w条数据)
        videos = session.exec(select(Video)).all()
        
        trend_map = {}
        
        for v in videos:
            # 确定日期键
            d_key = ""
            date_ref = v.created_at if hasattr(v, 'created_at') and v.created_at else None
            # 如果没有 created_at (旧数据)，用 finish_time 兜底，再不行忽略
            if not date_ref and v.finish_time:
                try: date_ref = datetime.datetime.strptime(v.finish_time, "%Y-%m-%d")
                except: pass
            
            if not date_ref: continue # 跳过无日期数据

            if dim == 'day': d_key = date_ref.strftime("%Y-%m-%d")
            elif dim == 'month': d_key = date_ref.strftime("%Y-%m")
            elif dim == 'week': d_key = date_ref.strftime("%Y-%W周")
            
            if d_key not in trend_map: trend_map[d_key] = {"in": 0, "out": 0}
            trend_map[d_key]["in"] += 1
            
            # 统计发布
            if v.status == "已发布" and v.publish_time:
                try:
                    p_date = datetime.datetime.strptime(v.publish_time[:10], "%Y-%m-%d")
                    p_key = ""
                    if dim == 'day': p_key = p_date.strftime("%Y-%m-%d")
                    elif dim == 'month': p_key = p_date.strftime("%Y-%m")
                    elif dim == 'week': p_key = p_date.strftime("%Y-%W周")
                    
                    if p_key not in trend_map: trend_map[p_key] = {"in": 0, "out": 0}
                    trend_map[p_key]["out"] += 1
                except: pass

        # 排序并转数组
        sorted_keys = sorted(trend_map.keys())
        # 只取最近 30 个单位的数据，防止图表太挤
        if len(sorted_keys) > 30: sorted_keys = sorted_keys[-30:]
        
        trend_data = {
            "dates": sorted_keys,
            "in": [trend_map[k]["in"] for k in sorted_keys],
            "out": [trend_map[k]["out"] for k in sorted_keys]
        }

        return {"platform": plat_data, "trend": trend_data}

# === 选项接口 ===
@main_app.get("/api/options")
def get_options():
    with Session(engine) as session:
        settings = {item.key: item.value.split(',') for item in session.exec(select(AppSettings)).all()}
        def get_merged(col, key):
            db_vals = session.exec(select(col).distinct()).all()
            clean = []
            for item in db_vals:
                if item and str(item) != 'nan': clean.extend([x.strip() for x in str(item).split(',')])
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

# === 列表查询 ===
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

# === 保存/上传 ===
@main_app.post("/api/upload")
async def upload_image(file: UploadFile):
    os.makedirs("assets/previews", exist_ok=True)
    ext = file.filename.split('.')[-1] if '.' in file.filename else "png"
    filename = f"upl_{uuid.uuid4().hex[:8]}.{ext}"
    with open(f"assets/previews/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return {"url": f"/assets/previews/{filename}"}

@main_app.post("/api/video/save")
async def save_video(
    id: Optional[str] = Form(None), # 允许接收 "temp" 或 int
    product_id: Optional[str] = Form(None), title: Optional[str] = Form(None),
    host: Optional[str] = Form(None), status: Optional[str] = Form(None),
    category: Optional[str] = Form(None), video_type: Optional[str] = Form(None),
    platform: Optional[str] = Form(None), finish_time: Optional[str] = Form(None),
    publish_time: Optional[str] = Form(None), remark: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None)
):
    with Session(engine) as session:
        # 新增逻辑：如果 ID 是 None, 'new', 'temp'，则创建新对象
        if not id or id in ['new', 'temp', 'undefined', 'null']:
            video = Video(
                product_id=product_id or "未命名", 
                title=title or "新建视频", 
                image_url="/assets/default.png",
                created_at=datetime.datetime.now() # 记录入库时间
            )
            session.add(video)
        else:
            # 编辑逻辑
            video = session.get(Video, int(id))
            if not video: raise HTTPException(404, "Not found")
        
        # 统一更新字段
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
        session.refresh(video)
        return {"message": "Saved", "id": video.id}

@main_app.delete("/api/video/{video_id}")
def delete_video(video_id: int):
    with Session(engine) as session:
        session.delete(session.get(Video, video_id))
        session.commit()
    return {"message": "Deleted"}

@main_app.get("/api/stats_summary") # 简单摘要
def get_stats_summary():
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
    return {"message": "ok"}