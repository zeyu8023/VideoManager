import os
import shutil
import math
import uuid
import datetime
from dateutil import parser # 需要确保环境支持，如果不行用自定义函数
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, desc, asc, text
from sqlalchemy import func
from typing import Optional

from .processor import process_excel_background
from .models import Video, AppSettings

main_app = FastAPI(title="VideoHub V16.0")
engine = create_engine("sqlite:///data/inventory.db")

# === 辅助工具：强力日期解析 ===
def parse_safe_date(date_str):
    """尝试将各种奇形怪状的字符串解析为 datetime 对象"""
    if not date_str or str(date_str).lower() in ['nan', 'none', '', 'nat']:
        return None
    try:
        # 截取前10位处理 YYYY-MM-DD
        date_str = str(date_str).strip()[:10]
        # 简单解析格式
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
    
    # 初始化默认配置
    with Session(engine) as session:
        defaults = {
            "hosts": "小梨,VIVI,七七,杨总,其他",
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

# === 核心：仪表盘聚合接口 (基于业务时间) ===
@main_app.get("/api/dashboard")
def get_dashboard_data(dim: str = "day"):
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        
        # 1. 基础计数
        total = len(videos)
        pending = sum(1 for v in videos if v.status == "待发布")
        
        # 2. 趋势统计容器
        # key: 日期字符串, value: {in:0, out:0}
        trend_map = {} 
        
        # 3. 周期统计 (今日/本月)
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")
        
        today_in = 0
        today_out = 0
        month_in = 0
        month_out = 0
        host_map = {} # 劳模统计

        for v in videos:
            # --- 解析时间 ---
            dt_finish = parse_safe_date(v.finish_time) # 入库依据
            dt_publish = parse_safe_date(v.publish_time) # 发布依据
            
            # --- 统计入库 (Finish Time) ---
            if dt_finish:
                d_str = dt_finish.strftime("%Y-%m-%d")
                m_str = dt_finish.strftime("%Y-%m")
                
                # 累加今日/本月
                if d_str == today_str: today_in += 1
                if m_str == month_str: month_in += 1
                
                # 累加趋势图
                k_trend = d_str # 默认按日
                if dim == 'month': k_trend = m_str
                elif dim == 'week': k_trend = dt_finish.strftime("%Y-W%W")
                
                if k_trend not in trend_map: trend_map[k_trend] = {"in": 0, "out": 0}
                trend_map[k_trend]["in"] += 1

            # --- 统计发布 (Publish Time) ---
            # 只有当状态是“已发布”且有时间，或者单纯有发布时间时统计
            # 这里逻辑宽容一点：只要有发布时间就算发布量
            if dt_publish:
                d_str = dt_publish.strftime("%Y-%m-%d")
                m_str = dt_publish.strftime("%Y-%m")
                
                if d_str == today_str: today_out += 1
                if m_str == month_str: month_out += 1
                
                k_trend = d_str
                if dim == 'month': k_trend = m_str
                elif dim == 'week': k_trend = dt_publish.strftime("%Y-W%W")
                
                if k_trend not in trend_map: trend_map[k_trend] = {"in": 0, "out": 0}
                trend_map[k_trend]["out"] += 1
                
                # 统计劳模 (仅统计有发布业绩的)
                if v.host:
                    for h in v.host.replace('，', ',').split(','):
                        h = h.strip()
                        if h: host_map[h] = host_map.get(h, 0) + 1

        # 4. 计算劳模
        top_host = max(host_map, key=host_map.get) if host_map else "暂无"

        # 5. 整理图表数据 (排序截取)
        sorted_keys = sorted(trend_map.keys())
        if len(sorted_keys) > 30: sorted_keys = sorted_keys[-30:] # 只看最近30个周期
        
        return {
            "total": total, "pending": pending, "top_host": top_host,
            "today_in": today_in, "today_out": today_out,
            "month_in": month_in, "month_out": month_out,
            "trend": {
                "dates": sorted_keys,
                "in": [trend_map[k]["in"] for k in sorted_keys],
                "out": [trend_map[k]["out"] for k in sorted_keys]
            }
        }

# === 全能筛选列表接口 ===
@main_app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, sort_by: str = "id", order: str = "desc",
    keyword: Optional[str] = None, 
    # 筛选字段
    host: Optional[str] = None, status: Optional[str] = None,
    category: Optional[str] = None, platform: Optional[str] = None, video_type: Optional[str] = None,
    product_id: Optional[str] = None, title: Optional[str] = None, remark: Optional[str] = None,
    # 时间范围筛选
    finish_start: Optional[str] = None, finish_end: Optional[str] = None,
    publish_start: Optional[str] = None, publish_end: Optional[str] = None
):
    with Session(engine) as session:
        stmt = select(Video)
        
        # 1. 搜索
        if keyword: stmt = stmt.where(or_(col(Video.title).contains(keyword), col(Video.product_id).contains(keyword), col(Video.remark).contains(keyword)))
        
        # 2. 文本精确/模糊筛选
        if product_id: stmt = stmt.where(col(Video.product_id).contains(product_id))
        if title: stmt = stmt.where(col(Video.title).contains(title))
        if remark: stmt = stmt.where(col(Video.remark).contains(remark))
        
        # 3. 下拉框筛选 (支持多选字段的模糊匹配)
        if host and "全部" not in host: stmt = stmt.where(col(Video.host).contains(host))
        if platform and "全部" not in platform: stmt = stmt.where(col(Video.platform).contains(platform))
        if category and "全部" not in category: stmt = stmt.where(Video.category == category)
        if status and "全部" not in status: stmt = stmt.where(Video.status == status)
        if video_type and "全部" not in video_type: stmt = stmt.where(Video.video_type == video_type)
        
        # 4. 时间范围筛选 (字符串比较)
        if finish_start: stmt = stmt.where(Video.finish_time >= finish_start)
        if finish_end: stmt = stmt.where(Video.finish_time <= finish_end)
        if publish_start: stmt = stmt.where(Video.publish_time >= publish_start)
        if publish_end: stmt = stmt.where(Video.publish_time <= publish_end)

        # 5. 排序分页
        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        sort_col = getattr(Video, sort_by, Video.id)
        stmt = stmt.order_by(asc(sort_col) if order == "asc" else desc(sort_col))
        stmt = stmt.offset((page - 1) * size).limit(size)
        
        return {"items": session.exec(stmt).all(), "total": total, "page": page, "size": size, "total_pages": math.ceil(total / size)}

# === 选项获取 ===
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

# === 增删改 ===
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
            video = Video(product_id=product_id or "", title=title or "", image_url="/assets/default.png")
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