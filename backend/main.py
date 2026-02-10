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

main_app = FastAPI(title="VideoHub V18.0 Matrix")
engine = create_engine("sqlite:///data/inventory.db")

# === 强力日期解析工具 ===
def parse_safe_date(date_str):
    if not date_str or str(date_str).lower() in ['nan', 'none', '', 'nat']:
        return None
    try:
        date_str = str(date_str).strip()[:10]
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.datetime.strptime(date_str, fmt)
            except:
                continue
    except:
        return None
    return None

@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    # 数据库自动修复
    with Session(engine) as session:
        try: session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except: 
            try: session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
            except: pass
            session.commit()
        
        session.exec(text(f"UPDATE video SET created_at = '{datetime.datetime.now()}' WHERE created_at IS NULL"))
        session.commit()

        defaults = {
            "hosts": "小梨,VIVI,七七,杨总,其他",
            "statuses": "待发布,已发布,剪辑中,拍摄中,脚本中",
            "categories": "球服,球鞋,球拍,周边,配件",
            "platforms": "抖音-炬鑫,小红书-有家,视频号-羽球,B站-官方",
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

# === 核心：矩阵仪表盘接口 ===
@main_app.get("/api/dashboard")
def get_dashboard_data(dim: str = "day"):
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        
        # 1. 基础库存指标
        total_assets = len(videos)
        pending = sum(1 for v in videos if v.status == "待发布")
        
        # 2. 时间窗口定义
        now = datetime.datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 本周一
        week_start = today_start - datetime.timedelta(days=now.weekday())
        # 本月1号
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 今年1月1号
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # 3. 统计容器
        # 库存流转统计
        flow_stats = {"today_in": 0, "today_out": 0, "month_in": 0, "month_out": 0}
        trend_map = {} # 日期: {in, out}
        
        # 结构统计
        host_map = {}
        type_map = {}
        plat_dist_map = {} # 平台分发统计
        
        # 矩阵统计 {account_name: {day, week, month, year}}
        matrix_map = {}
        total_distribution_count = 0 # 总分发量

        for v in videos:
            dt_finish = parse_safe_date(v.finish_time)
            dt_publish = parse_safe_date(v.publish_time)
            
            # --- A. 库存入库统计 ---
            if dt_finish:
                d_str = dt_finish.strftime("%Y-%m-%d")
                m_str = dt_finish.strftime("%Y-%m")
                
                if dt_finish >= today_start: flow_stats["today_in"] += 1
                if dt_finish >= month_start: flow_stats["month_in"] += 1
                
                # 趋势图 key
                k_trend = d_str
                if dim == 'month': k_trend = m_str
                elif dim == 'week': k_trend = dt_finish.strftime("%Y-W%W")
                
                if k_trend not in trend_map: trend_map[k_trend] = {"in": 0, "out": 0}
                trend_map[k_trend]["in"] += 1

            # --- B. 发布与分发统计 (核心升级) ---
            if dt_publish:
                d_str = dt_publish.strftime("%Y-%m-%d")
                m_str = dt_publish.strftime("%Y-%m")
                
                if dt_publish >= today_start: flow_stats["today_out"] += 1
                if dt_publish >= month_start: flow_stats["month_out"] += 1
                
                k_trend = d_str
                if dim == 'month': k_trend = m_str
                elif dim == 'week': k_trend = dt_publish.strftime("%Y-W%W")
                
                if k_trend not in trend_map: trend_map[k_trend] = {"in": 0, "out": 0}
                trend_map[k_trend]["out"] += 1
                
                # === C. 矩阵账号统计 ===
                # 只有“已发布”且有时间的才算有效分发
                if v.status == "已发布" and v.platform:
                    # 拆分多选平台 (例如 "抖音-A, 小红书-B")
                    accounts = [p.strip() for p in v.platform.replace('，', ',').split(',') if p.strip()]
                    
                    for acc in accounts:
                        total_distribution_count += 1
                        
                        # 初始化账号数据
                        if acc not in matrix_map: 
                            matrix_map[acc] = {"day": 0, "week": 0, "month": 0, "year": 0}
                        
                        # 累加各时间维度
                        if dt_publish >= today_start: matrix_map[acc]["day"] += 1
                        if dt_publish >= week_start: matrix_map[acc]["week"] += 1
                        if dt_publish >= month_start: matrix_map[acc]["month"] += 1
                        if dt_publish >= year_start: matrix_map[acc]["year"] += 1
                        
                        # 同时也统计雷达图数据
                        plat_dist_map[acc] = plat_dist_map.get(acc, 0) + 1

            # --- D. 其他结构统计 ---
            if v.host and dt_finish: # 主播按产出算
                for h in v.host.replace('，', ',').split(','):
                    h = h.strip()
                    if h: host_map[h] = host_map.get(h, 0) + 1
            
            if v.video_type:
                type_map[v.video_type] = type_map.get(v.video_type, 0) + 1

        # 4. 数据格式化
        # 趋势图
        sorted_keys = sorted(trend_map.keys())[-30:]
        
        # 矩阵列表 (按年发布量倒序)
        matrix_list = [{"name": k, **v} for k, v in matrix_map.items()]
        matrix_list.sort(key=lambda x: x["year"], reverse=True)

        return {
            "kpi": {
                "total": total_assets, 
                "pending": pending,
                "dist_total": total_distribution_count, # 新增：累计分发
                "today_in": flow_stats["today_in"], "today_out": flow_stats["today_out"],
                "month_in": flow_stats["month_in"], "month_out": flow_stats["month_out"]
            },
            "trend": {
                "dates": sorted_keys,
                "in": [trend_map[k]["in"] for k in sorted_keys],
                "out": [trend_map[k]["out"] for k in sorted_keys]
            },
            "matrix": matrix_list, # 新增：矩阵表数据
            "hosts": sorted([{"name": k, "value": v} for k, v in host_map.items()], key=lambda x:x['value'], reverse=True)[:5],
            "types": [{"name": k, "value": v} for k, v in type_map.items()],
            "plats": [{"name": k, "value": v} for k, v in plat_dist_map.items()]
        }

# === 列表接口 (保持 V16 全功能) ===
@main_app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, sort_by: str = "id", order: str = "desc",
    keyword: Optional[str] = None, 
    host: Optional[str] = None, status: Optional[str] = None,
    category: Optional[str] = None, platform: Optional[str] = None, video_type: Optional[str] = None,
    product_id: Optional[str] = None, title: Optional[str] = None, remark: Optional[str] = None,
    finish_start: Optional[str] = None, finish_end: Optional[str] = None,
    publish_start: Optional[str] = None, publish_end: Optional[str] = None
):
    with Session(engine) as session:
        stmt = select(Video)
        if keyword: stmt = stmt.where(or_(col(Video.title).contains(keyword), col(Video.product_id).contains(keyword), col(Video.remark).contains(keyword)))
        if product_id: stmt = stmt.where(col(Video.product_id).contains(product_id))
        if title: stmt = stmt.where(col(Video.title).contains(title))
        if remark: stmt = stmt.where(col(Video.remark).contains(remark))
        if host and "全部" not in host: stmt = stmt.where(col(Video.host).contains(host))
        if platform and "全部" not in platform: stmt = stmt.where(col(Video.platform).contains(platform))
        if category and "全部" not in category: stmt = stmt.where(Video.category == category)
        if status and "全部" not in status: stmt = stmt.where(Video.status == status)
        if video_type and "全部" not in video_type: stmt = stmt.where(Video.video_type == video_type)
        if finish_start: stmt = stmt.where(Video.finish_time >= finish_start)
        if finish_end: stmt = stmt.where(Video.finish_time <= finish_end)
        if publish_start: stmt = stmt.where(Video.publish_time >= publish_start)
        if publish_end: stmt = stmt.where(Video.publish_time <= publish_end)

        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        sort_col = getattr(Video, sort_by, Video.id)
        stmt = stmt.order_by(asc(sort_col) if order == "asc" else desc(sort_col))
        stmt = stmt.offset((page - 1) * size).limit(size)
        return {"items": session.exec(stmt).all(), "total": total, "page": page, "size": size, "total_pages": math.ceil(total / size)}

# === 通用接口 (保持不变) ===
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
        if not id or id in ['new', 'temp', 'undefined']:
            video = Video(product_id=product_id or "", title=title or "", image_url="/assets/default.png", created_at=datetime.datetime.now())
            session.add(video)
        else:
            video = session.get(Video, int(id))
            if not video: raise HTTPException(404)
        
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