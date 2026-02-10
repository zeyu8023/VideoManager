import os
import shutil
import math
import uuid
import datetime
import logging
import re
from typing import Optional

from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, desc, asc, text
from sqlalchemy import func

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VideoHub")

main_app = FastAPI(title="VideoHub V30.0 Pure Stats")
engine = create_engine("sqlite:///data/inventory.db")

# 注意：删除了 Product 表定义，只保留核心 Video
from .models import Video, AppSettings

# === 强力工具：安全转字符串 (防止报错核心) ===
def safe_str(val):
    if val is None: return ""
    return str(val).strip()

# === 强力工具：日期解析 ===
def parse_safe_date(date_str):
    s = safe_str(date_str).lower()
    if not s or s in ['nan', 'none', '', 'nat', 'null']: return None
    try:
        # 1. 优先截取前10位标准格式
        clean_s = s[:10]
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
            try: return datetime.datetime.strptime(clean_s, fmt)
            except: continue
        # 2. 失败则尝试正则提取
        match = re.search(r'(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})', s)
        if match:
            return datetime.datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except: pass
    return None

# === 初始化 ===
@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        try: session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except: 
            try: session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
            except: pass
            session.commit()
        
        session.exec(text("UPDATE video SET created_at = finish_time WHERE created_at IS NULL AND finish_time IS NOT NULL"))
        session.exec(text(f"UPDATE video SET created_at = '{datetime.datetime.now()}' WHERE created_at IS NULL"))
        
        defaults = {
            "hosts": "小梨,VIVI,七七,杨总,其他",
            "statuses": "待发布,已发布,剪辑中,拍摄中,脚本中",
            "categories": "球服,球鞋,球拍,周边,配件",
            "platforms": "抖音-炬鑫,小红书-有家,视频号-羽球,B站-官方,快手-炬鑫",
            "video_types": "产品展示,剧情,口播,Vlog,花絮"
        }
        for k, v in defaults.items():
            if not session.get(AppSettings, k): session.add(AppSettings(key=k, value=v))
        session.commit()

# 挂载静态文件
# 确保您的目录结构是 frontend/static
if not os.path.exists("frontend/static"):
    os.makedirs("frontend/static", exist_ok=True)

main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")
# 注意：这里挂载的是 /static 路径，对应 frontend/static 文件夹
main_app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# === 接口 1: 仪表盘 ===
@main_app.get("/api/dashboard")
def get_dashboard_data(dim: str = "day"):
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        total = len(videos)
        pending = sum(1 for v in videos if safe_str(v.status) == "待发布")
        
        now = datetime.datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        flow = {"t_in":0, "t_out":0, "m_in":0, "m_out":0}
        trend = {}
        hosts = {}
        types = {}
        plats = {}
        matrix = {}
        dist = 0

        for v in videos:
            t_in = parse_safe_date(v.finish_time)
            t_pub = parse_safe_date(v.publish_time)
            v_stat = safe_str(v.status)
            v_plat = safe_str(v.platform)
            
            # 入库统计
            if t_in:
                if t_in >= today: flow["t_in"] += 1
                if t_in >= month: flow["m_in"] += 1
                
                k = t_in.strftime("%Y-%m-%d")
                if dim=='month': k=t_in.strftime("%Y-%m")
                elif dim=='week': k=t_in.strftime("%Y-W%W")
                
                if k not in trend: trend[k] = {"in":0, "out":0}
                trend[k]["in"] += 1
                
                if v.host:
                    for h in safe_str(v.host).replace('，', ',').split(','):
                        h = h.strip()
                        if h: hosts[h] = hosts.get(h, 0) + 1

            # 发布统计
            if t_pub:
                if t_pub >= today: flow["t_out"] += 1
                if t_pub >= month: flow["m_out"] += 1
                
                k = t_pub.strftime("%Y-%m-%d")
                if dim=='month': k=t_pub.strftime("%Y-%m")
                elif dim=='week': k=t_pub.strftime("%Y-W%W")
                
                if k not in trend: trend[k] = {"in":0, "out":0}
                trend[k]["out"] += 1
                
                if v_stat == "已发布" and v_plat:
                    accs = [p.strip() for p in v_plat.replace('，', ',').split(',') if p.strip()]
                    for acc in accs:
                        dist += 1
                        if acc not in matrix: matrix[acc] = {"day":0, "week":0, "month":0, "year":0}
                        if t_pub >= today: matrix[acc]["day"] += 1
                        if t_pub >= month: matrix[acc]["month"] += 1
                        matrix[acc]["year"] += 1
                        plats[acc] = plats.get(acc, 0) + 1
            
            if v.video_type:
                vt = safe_str(v.video_type)
                types[vt] = types.get(vt, 0) + 1

        dates = sorted(trend.keys())[-30:]
        mat_list = [{"name":k, **v} for k,v in matrix.items()]
        mat_list.sort(key=lambda x:x["year"], reverse=True)
        host_list = sorted([{"name":k, "value":v} for k,v in hosts.items()], key=lambda x:x['value'], reverse=True)[:5]
        
        return {
            "kpi": {"total":total, "pending":pending, "dist":dist, "t_in":flow["t_in"], "t_out":flow["t_out"], "m_in":flow["m_in"], "m_out":flow["m_out"]},
            "trend": {"dates":dates, "in":[trend[k]["in"] for k in dates], "out":[trend[k]["out"] for k in dates]},
            "matrix": mat_list, "hosts": host_list, 
            "types": [{"name":k, "value":v} for k,v in types.items()], 
            "plats": [{"name":k, "value":v} for k,v in plats.items()]
        }

# === 接口 2: 产品统计 (纯净统计版) ===
@main_app.get("/api/product_stats")
def get_product_stats():
    with Session(engine) as session:
        # 只查询 Video 表，不做任何额外关联，确保极速且稳定
        videos = session.exec(select(Video)).all()
        
        stats = {}
        for v in videos:
            # === 核心修复 ===
            # 无论 product_id 是 int 还是 float，强制转 str，避免 strip() 报错
            pid_raw = v.product_id
            if pid_raw is None:
                pid = "未分类"
            else:
                pid = str(pid_raw).strip() # 这里的 str() 是救命稻草
                if pid.lower() in ['nan', 'none', '']:
                    pid = "未分类"
            
            if pid not in stats: 
                stats[pid] = {"name": pid, "total": 0, "pending": 0}
            
            stats[pid]["total"] += 1
            # 状态也做安全转换
            if safe_str(v.status) == "待发布": 
                stats[pid]["pending"] += 1
        
        res = list(stats.values())
        # 排序：优先显示积压多的
        res.sort(key=lambda x: (x["pending"], x["total"]), reverse=True)
        return res

# === 接口 3: 列表查询 (保持功能) ===
@main_app.get("/api/videos")
def list_videos(page: int=1, size: int=100, sort_by: str="id", order: str="desc", keyword: Optional[str]=None, host: Optional[str]=None, status: Optional[str]=None, category: Optional[str]=None, platform: Optional[str]=None, video_type: Optional[str]=None, product_id: Optional[str]=None, title: Optional[str]=None, remark: Optional[str]=None, finish_start: Optional[str]=None, finish_end: Optional[str]=None, publish_start: Optional[str]=None, publish_end: Optional[str]=None):
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
        stmt = stmt.order_by(asc(getattr(Video, sort_by)) if order=="asc" else desc(getattr(Video, sort_by))).offset((page-1)*size).limit(size)
        return {"items": session.exec(stmt).all(), "total": total, "page": page, "size": size, "total_pages": math.ceil(total/size)}

@main_app.post("/api/video/save")
async def save_video(id: Optional[str]=Form(None), product_id: Optional[str]=Form(None), title: Optional[str]=Form(None), host: Optional[str]=Form(None), status: Optional[str]=Form(None), category: Optional[str]=Form(None), video_type: Optional[str]=Form(None), platform: Optional[str]=Form(None), finish_time: Optional[str]=Form(None), publish_time: Optional[str]=Form(None), remark: Optional[str]=Form(None), image_url: Optional[str]=Form(None)):
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
    return {"message": "ok"}

@main_app.get("/api/options")
def get_options():
    with Session(engine) as session:
        settings = {i.key: i.value.split(',') for i in session.exec(select(AppSettings)).all()}
        def merge(col, k):
            db = session.exec(select(col).distinct()).all()
            clean = []
            for i in db: 
                if i and str(i).lower() not in ['nan', 'none', '']: clean.extend([x.strip() for x in str(i).replace('，', ',').split(',')])
            return sorted(list(set(clean + [x.strip() for x in settings.get(k, []) if x.strip()])))
        return {
            "hosts": merge(Video.host, "hosts"), "categories": merge(Video.category, "categories"), "statuses": merge(Video.status, "statuses"),
            "platforms": merge(Video.platform, "platforms"), "video_types": merge(Video.video_type, "video_types"), "product_ids": merge(Video.product_id, "ignore")
        }

@main_app.post("/api/settings")
def update_settings(key: str=Form(...), value: str=Form(...)):
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
    name = f"upl_{uuid.uuid4().hex[:8]}.{ext}"
    with open(f"assets/previews/{name}", "wb") as f: shutil.copyfileobj(file.file, f)
    return {"url": f"/assets/previews/{name}"}

@main_app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    if not os.path.exists("temp_uploads"): raise HTTPException(404)
    files = [f for f in os.listdir("temp_uploads") if f.endswith(".xlsx")]
    if not files: raise HTTPException(404)
    from .processor import process_excel_background 
    bg_tasks.add_task(process_excel_background, os.path.join("temp_uploads", files[0]), engine)
    return {"message": "started"}