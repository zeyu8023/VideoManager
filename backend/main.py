import os
import shutil
import math
import uuid
import datetime
import logging
from typing import Optional

from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, desc, asc, text, Field
from sqlalchemy import func

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VideoHub")

main_app = FastAPI(title="VideoHub V26.2 Product Image & Search")
engine = create_engine("sqlite:///data/inventory.db")

# === 模型定义 (新增 Product) ===
# 原有的 Video 和 AppSettings 保持不变，这里省略定义，假设它们在 .models 中
# 如果你没有单独的 .models 文件，请确保之前的 Video 和 AppSettings 类定义在这里
from .models import Video, AppSettings 

class Product(SQLModel, table=True):
    name: str = Field(primary_key=True) # 产品编号/名称作为主键
    image_url: Optional[str] = None
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.now)

# === 工具函数 ===
def parse_safe_date(date_str):
    if not date_str or str(date_str).lower() in ['nan', 'none', '', 'nat', 'null']: return None
    try:
        date_str = str(date_str).strip()[:10]
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
            try: return datetime.datetime.strptime(date_str, fmt)
            except: continue
    except: return None
    return None

# === 初始化 ===
@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine) # 自动创建新的 Product 表
    
    with Session(engine) as session:
        # (旧的迁移逻辑保持不变...)
        try: session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except: 
            try: session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
            except: pass
            session.commit()
        
        session.exec(text("UPDATE video SET created_at = finish_time WHERE created_at IS NULL AND finish_time IS NOT NULL"))
        session.exec(text(f"UPDATE video SET created_at = '{datetime.datetime.now()}' WHERE created_at IS NULL"))
        session.commit()

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

main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# === 接口: 仪表盘 (保持不变) ===
@main_app.get("/api/dashboard")
def get_dashboard_data(dim: str = "day"):
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        total_assets = len(videos)
        pending = sum(1 for v in videos if v.status == "待发布")
        
        now = datetime.datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - datetime.timedelta(days=now.weekday())
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        flow = {"today_in":0, "today_out":0, "month_in":0, "month_out":0}
        trend = {}
        hosts = {}
        types = {}
        plats = {}
        matrix = {}
        dist_total = 0

        for v in videos:
            fin = parse_safe_date(v.finish_time)
            pub = parse_safe_date(v.publish_time)
            
            # 入库
            if fin:
                d_str = fin.strftime("%Y-%m-%d")
                m_str = fin.strftime("%Y-%m")
                if fin >= today_start: flow["today_in"] += 1
                if fin >= month_start: flow["month_in"] += 1
                
                k = d_str
                if dim == 'month': k = m_str
                elif dim == 'week': k = fin.strftime("%Y-W%W")
                if k not in trend: trend[k] = {"in":0, "out":0}
                trend[k]["in"] += 1
                
                if v.host:
                    for h in v.host.replace('，', ',').split(','):
                        h = h.strip()
                        if h: hosts[h] = hosts.get(h, 0) + 1

            # 发布
            if pub:
                d_str = pub.strftime("%Y-%m-%d")
                m_str = pub.strftime("%Y-%m")
                if pub >= today_start: flow["today_out"] += 1
                if pub >= month_start: flow["month_out"] += 1
                
                k = d_str
                if dim == 'month': k = m_str
                elif dim == 'week': k = pub.strftime("%Y-W%W")
                if k not in trend: trend[k] = {"in":0, "out":0}
                trend[k]["out"] += 1
                
                if v.status == "已发布" and v.platform:
                    accs = [p.strip() for p in v.platform.replace('，', ',').split(',') if p.strip()]
                    for acc in accs:
                        dist_total += 1
                        if acc not in matrix: matrix[acc] = {"day":0, "week":0, "month":0, "year":0}
                        if pub >= today_start: matrix[acc]["day"] += 1
                        if pub >= week_start: matrix[acc]["week"] += 1
                        if pub >= month_start: matrix[acc]["month"] += 1
                        if pub >= year_start: matrix[acc]["year"] += 1
                        plats[acc] = plats.get(acc, 0) + 1
            
            if v.video_type: types[v.video_type] = types.get(v.video_type, 0) + 1

        dates = sorted(trend.keys())[-30:]
        mat_list = [{"name":k, **v} for k,v in matrix.items()]
        mat_list.sort(key=lambda x:x["year"], reverse=True)
        host_list = sorted([{"name":k, "value":v} for k,v in hosts.items()], key=lambda x:x['value'], reverse=True)[:5]
        type_list = [{"name":k, "value":v} for k,v in types.items()]
        plat_list = [{"name":k, "value":v} for k,v in plats.items()]

        return {
            "kpi": {"total":total_assets, "pending":pending, "dist":dist_total, "t_in":flow["today_in"], "t_out":flow["today_out"], "m_in":flow["month_in"], "m_out":flow["month_out"]},
            "trend": {"dates":dates, "in":[trend[k]["in"] for k in dates], "out":[trend[k]["out"] for k in dates]},
            "matrix": mat_list, "hosts": host_list, "types": type_list, "plats": plat_list
        }

# === 接口 2: 产品统计 (升级版：带图片) ===
@main_app.get("/api/product_stats")
def get_product_stats():
    with Session(engine) as session:
        # 1. 先统计库存数据
        videos = session.exec(select(Video.product_id, Video.status)).all()
        stats = {}
        for pid, status in videos:
            if not pid: pid = "未分类"
            pid = pid.strip()
            if pid not in stats: stats[pid] = {"name": pid, "total": 0, "pending": 0, "image_url": None}
            stats[pid]["total"] += 1
            if status == "待发布": stats[pid]["pending"] += 1
        
        # 2. 再查 Product 表获取图片
        product_imgs = session.exec(select(Product)).all()
        img_map = {p.name: p.image_url for p.name in product_imgs}
        
        # 3. 合并数据
        for pid, data in stats.items():
            data["image_url"] = img_map.get(pid, None) # 如果没有图，就是 None

        res = list(stats.values())
        # 排序：优先显示有积压的，其次是总数多的
        res.sort(key=lambda x: (x["pending"], x["total"]), reverse=True)
        return res

# === 新增接口: 保存产品图片 ===
@main_app.post("/api/product/save_image")
def save_product_image(name: str = Form(...), image_url: str = Form(...)):
    with Session(engine) as session:
        product = session.get(Product, name)
        if not product:
            product = Product(name=name, image_url=image_url)
        else:
            product.image_url = image_url
            product.updated_at = datetime.datetime.now()
        session.add(product)
        session.commit()
    return {"message": "Product image saved", "url": image_url}


# === 接口 3: 列表查询 (保持不变) ===
@main_app.get("/api/videos")
def list_videos(
    page: int=1, size: int=100, sort_by: str="id", order: str="desc",
    keyword: Optional[str]=None, host: Optional[str]=None, status: Optional[str]=None,
    category: Optional[str]=None, platform: Optional[str]=None, video_type: Optional[str]=None,
    product_id: Optional[str]=None, title: Optional[str]=None, remark: Optional[str]=None,
    finish_start: Optional[str]=None, finish_end: Optional[str]=None,
    publish_start: Optional[str]=None, publish_end: Optional[str]=None
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
    # 注意：确保 processor.py 也存在并能正确导入
    from .processor import process_excel_background 
    bg_tasks.add_task(process_excel_background, os.path.join("temp_uploads", files[0]), engine)
    return {"message": "started"}