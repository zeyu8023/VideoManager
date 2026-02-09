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

main_app = FastAPI(title="VideoHub V15.0 Enterprise")
engine = create_engine("sqlite:///data/inventory.db")

@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    # === 数据库自动维护 ===
    with Session(engine) as session:
        # 1. 补全 created_at
        try: session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except: 
            try: session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
            except: pass
            session.commit()
        # 2. 修复旧数据时间 (防止统计为0)
        session.exec(text(f"UPDATE video SET created_at = '{datetime.datetime.now()}' WHERE created_at IS NULL"))
        session.commit()

        # 3. 初始化配置 (防止下拉框为空)
        defaults = {
            "hosts": "小梨,VIVI,七七,杨总",
            "statuses": "待发布,已发布,剪辑中,拍摄中,脚本中",
            "categories": "球服,球鞋,球拍,周边,配件",
            "platforms": "抖音,小红书,视频号,B站,快手",
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

# === 核心：仪表盘聚合接口 ===
@main_app.get("/api/dashboard")
def get_dashboard_data():
    with Session(engine) as session:
        now = datetime.datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # 1. 基础指标
        total = session.exec(select(func.count(Video.id))).one()
        pending = session.exec(select(func.count(Video.id)).where(Video.status == "待发布")).one()
        
        # 2. 今日/本月数据
        today_in = session.exec(select(func.count(Video.id)).where(Video.created_at >= today_start)).one()
        month_in = session.exec(select(func.count(Video.id)).where(Video.created_at >= month_start)).one()
        
        # 发布数据需转换字符串日期 (兼容性处理)
        # 简单起见，这里取所有数据在内存做日期比对 (适用于 <10w 数据量)
        videos = session.exec(select(Video)).all()
        today_out = 0
        month_out = 0
        host_map = {}
        
        trend_map = {} # {date: {in:0, out:0}}
        
        for v in videos:
            # 统计发布量
            if v.status == "已发布" and v.publish_time:
                try:
                    p_dt = datetime.datetime.strptime(v.publish_time[:10], "%Y-%m-%d")
                    if p_dt >= today_start: today_out += 1
                    if p_dt >= month_start: month_out += 1
                    
                    # 趋势图数据 (发布)
                    d_str = p_dt.strftime("%Y-%m-%d")
                    if d_str not in trend_map: trend_map[d_str] = {"in": 0, "out": 0}
                    trend_map[d_str]["out"] += 1
                    
                    # 劳模统计 (多选拆分)
                    if v.host:
                        for h in v.host.replace('，', ',').split(','):
                            h = h.strip()
                            if h: host_map[h] = host_map.get(h, 0) + 1
                except: pass
            
            # 趋势图数据 (入库)
            if v.created_at:
                c_str = v.created_at.strftime("%Y-%m-%d")
                if c_str not in trend_map: trend_map[c_str] = {"in": 0, "out": 0}
                trend_map[c_str]["in"] += 1

        # 计算劳模
        top_host = "暂无"
        if host_map:
            top_host = max(host_map, key=host_map.get)

        # 整理趋势图 (最近15天)
        sorted_dates = sorted(trend_map.keys())[-15:]
        trend_data = {
            "dates": sorted_dates,
            "in": [trend_map[d]["in"] for d in sorted_dates],
            "out": [trend_map[d]["out"] for d in sorted_dates]
        }

        return {
            "total": total, "pending": pending, "top_host": top_host,
            "today_in": today_in, "today_out": today_out,
            "month_in": month_in, "month_out": month_out,
            "trend": trend_data
        }

# === 视频库存管理接口 ===
@main_app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, sort_by: str = "id", order: str = "desc",
    keyword: Optional[str] = None, 
    host: Optional[str] = None, status: Optional[str] = None,
    category: Optional[str] = None, platform: Optional[str] = None, video_type: Optional[str] = None,
    product_id: Optional[str] = None, title: Optional[str] = None,
    pub_start: Optional[str] = None, pub_end: Optional[str] = None,
    fin_start: Optional[str] = None, fin_end: Optional[str] = None
):
    with Session(engine) as session:
        stmt = select(Video)
        
        # 搜索与筛选
        if keyword: stmt = stmt.where(or_(col(Video.title).contains(keyword), col(Video.product_id).contains(keyword), col(Video.remark).contains(keyword)))
        if product_id: stmt = stmt.where(col(Video.product_id).contains(product_id))
        if title: stmt = stmt.where(col(Video.title).contains(title))
        
        # 多选模糊匹配
        if host and host != "全部": stmt = stmt.where(col(Video.host).contains(host))
        if platform and platform != "全部": stmt = stmt.where(col(Video.platform).contains(platform))
        
        # 精确匹配
        if category and category != "全部": stmt = stmt.where(Video.category == category)
        if status and status != "全部": stmt = stmt.where(Video.status == status)
        if video_type and video_type != "全部": stmt = stmt.where(Video.video_type == video_type)
        
        # 时间范围
        if pub_start: stmt = stmt.where(Video.publish_time >= pub_start)
        if pub_end: stmt = stmt.where(Video.publish_time <= pub_end)
        if fin_start: stmt = stmt.where(Video.finish_time >= fin_start)
        if fin_end: stmt = stmt.where(Video.finish_time <= fin_end)

        # 排序分页
        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        sort_col = getattr(Video, sort_by, Video.id)
        stmt = stmt.order_by(asc(sort_col) if order == "asc" else desc(sort_col))
        stmt = stmt.offset((page - 1) * size).limit(size)
        
        return {"items": session.exec(stmt).all(), "total": total, "page": page, "size": size, "total_pages": math.ceil(total / size)}

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
        # 兼容 "new", "temp", undefined 等前端传来的临时ID
        if not id or id in ['new', 'temp', 'undefined', 'null']:
            video = Video(
                product_id=product_id or "", 
                title=title or "", 
                image_url="/assets/default.png",
                created_at=datetime.datetime.now()
            )
            session.add(video)
        else:
            video = session.get(Video, int(id))
            if not video: raise HTTPException(404, "Not found")
        
        # 允许空值更新
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
        return {"message": "ok"}

@main_app.delete("/api/video/{video_id}")
def delete_video(video_id: int):
    with Session(engine) as session:
        session.delete(session.get(Video, video_id))
        session.commit()
    return {"message": "deleted"}

# === 配置与工具 ===
@main_app.get("/api/options")
def get_options():
    with Session(engine) as session:
        settings = {item.key: item.value.split(',') for item in session.exec(select(AppSettings)).all()}
        def merge(col, key):
            db = session.exec(select(col).distinct()).all()
            clean = []
            for i in db:
                if i and str(i).lower() not in ['nan', 'none', '']:
                    clean.extend([x.strip() for x in str(i).replace('，', ',').split(',')])
            preset = [x.strip() for x in settings.get(key, []) if x.strip()]
            return sorted(list(set(clean + preset)))
        return {
            "hosts": merge(Video.host, "hosts"),
            "categories": merge(Video.category, "categories"),
            "statuses": merge(Video.status, "statuses"),
            "platforms": merge(Video.platform, "platforms"),
            "video_types": merge(Video.video_type, "video_types"),
            "product_ids": merge(Video.product_id, "ignore")
        }

@main_app.post("/api/settings")
def update_settings(key: str = Form(...), value: str = Form(...)):
    with Session(engine) as session:
        s = session.get(AppSettings, key)
        if not s: s = AppSettings(key=key, value=value)
        else: s.value = value
        session.add(s)
        session.commit()
    return {"message": "ok"}

@main_app.post("/api/upload")
async def upload_image(file: UploadFile):
    os.makedirs("assets/previews", exist_ok=True)
    ext = file.filename.split('.')[-1] if '.' in file.filename else "png"
    filename = f"upl_{uuid.uuid4().hex[:8]}.{ext}"
    with open(f"assets/previews/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return {"url": f"/assets/previews/{filename}"}

@main_app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    if not os.path.exists("temp_uploads"): raise HTTPException(404)
    files = [f for f in os.listdir("temp_uploads") if f.endswith(".xlsx")]
    if not files: raise HTTPException(404)
    bg_tasks.add_task(process_excel_background, os.path.join("temp_uploads", files[0]), engine)
    return {"message": "started"}