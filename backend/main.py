import os
import shutil
import math
import uuid
import datetime
import logging
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_, desc, asc, text
from sqlalchemy import func
from pydantic import BaseModel

# 引入项目内部模块
from .processor import process_excel_background
from .models import Video, AppSettings

# ==========================================
# 1. 系统配置与初始化
# ==========================================

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VideoHub")

app = FastAPI(
    title="VideoHub V24.0 Enterprise Edition",
    description="全功能视频库存管理系统 - 含仪表盘、SPU管理、矩阵分析",
    version="24.0.0"
)

# 数据库连接
DB_URL = "sqlite:///data/inventory.db"
engine = create_engine(DB_URL, echo=False)  # echo=True 可打印 SQL 用于调试

# ------------------------------------------
# 工具函数
# ------------------------------------------

def parse_safe_date(date_str: str) -> Optional[datetime.datetime]:
    """
    鲁棒的日期解析函数。
    能够处理 Excel 导入产生的各种奇怪日期格式。
    支持: '2023-01-01', '2023/01/01', '20230101', '2023-01-01 12:00:00' 等
    """
    if not date_str:
        return None
    
    s = str(date_str).strip().lower()
    if s in ['nan', 'none', '', 'nat', 'null', 'undefined']:
        return None
    
    # 截取前10位处理 YYYY-MM-DD
    s_clean = s[:10]
    
    formats = [
        "%Y-%m-%d", 
        "%Y/%m/%d", 
        "%Y%m%d", 
        "%Y.%m.%d"
    ]
    
    for fmt in formats:
        try:
            return datetime.datetime.strptime(s_clean, fmt)
        except ValueError:
            continue
            
    return None

# ------------------------------------------
# 生命周期事件
# ------------------------------------------

@app.on_event("startup")
def on_startup():
    logger.info("系统启动中，正在检查环境...")
    
    # 1. 创建必要目录
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    
    # 2. 初始化数据库表结构
    SQLModel.metadata.create_all(engine)
    
    # 3. 数据库结构自动迁移 (Auto Migration)
    # 检查并添加 created_at 字段，防止旧版数据库报错
    with Session(engine) as session:
        try:
            session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except Exception: 
            logger.warning("检测到旧版数据库，正在自动添加 created_at 字段...")
            try: 
                session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
                session.commit()
                logger.info("数据库迁移成功！")
            except Exception as e: 
                logger.error(f"数据库迁移失败: {e}")
        
        # 4. 数据清洗：给旧数据补全时间
        # 逻辑：优先用 finish_time 补，没有就用当前时间
        logger.info("正在执行数据完整性检查...")
        session.exec(text("UPDATE video SET created_at = finish_time WHERE created_at IS NULL AND finish_time IS NOT NULL"))
        session.exec(text(f"UPDATE video SET created_at = '{datetime.datetime.now()}' WHERE created_at IS NULL"))
        session.commit()

        # 5. 初始化默认全局配置
        _init_settings(session)
        
    logger.info("系统启动完成，服务已就绪。")

def _init_settings(session: Session):
    """初始化下拉框选项"""
    defaults = {
        "hosts": "小梨,VIVI,七七,杨总,其他",
        "statuses": "待发布,已发布,剪辑中,拍摄中,脚本中",
        "categories": "球服,球鞋,球拍,周边,配件",
        "platforms": "抖音-炬鑫,小红书-有家,视频号-羽球,B站-官方,快手-炬鑫",
        "video_types": "产品展示,剧情,口播,Vlog,花絮"
    }
    for k, v in defaults.items():
        if not session.get(AppSettings, k):
            session.add(AppSettings(key=k, value=v))
            logger.info(f"初始化配置项: {k}")
    session.commit()

# 挂载静态文件
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# ==========================================
# 2. 页面路由
# ==========================================

@app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# ==========================================
# 3. 核心统计接口 (Dashboard)
# ==========================================

@app.get("/api/dashboard")
def get_dashboard_data(dim: str = "day"):
    """
    全能仪表盘数据接口
    dim: 趋势图的时间维度 (day, week, month)
    """
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        
        # 定义时间窗口
        now = datetime.datetime.now()
        time_windows = {
            "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
            "week": now.replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=now.weekday()),
            "month": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            "year": now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        }
        
        # 初始化统计容器
        stats = {
            "total": len(videos),
            "pending": 0,
            "dist_total": 0,
            "flow": {"today_in": 0, "today_out": 0, "month_in": 0, "month_out": 0},
            "trend": {},
            "hosts": {},
            "types": {},
            "plats": {},
            "matrix": {}
        }

        # 遍历所有视频进行统计
        for v in videos:
            _process_video_stats(v, stats, time_windows, dim)

        # 数据后处理：排序、截取、格式化
        result = _format_dashboard_response(stats)
        return result

def _process_video_stats(v: Video, stats: dict, windows: dict, dim: str):
    """单条视频的统计逻辑拆分"""
    
    # 1. 统计待发布
    if v.status == "待发布":
        stats["pending"] += 1
        
    # 解析时间
    dt_fin = parse_safe_date(v.finish_time)
    dt_pub = parse_safe_date(v.publish_time)
    
    # 2. 入库统计 (基于完成时间)
    if dt_fin:
        if dt_fin >= windows["today"]: stats["flow"]["today_in"] += 1
        if dt_fin >= windows["month"]: stats["flow"]["month_in"] += 1
        
        # 趋势图 (In)
        k_trend = _get_trend_key(dt_fin, dim)
        if k_trend not in stats["trend"]: stats["trend"][k_trend] = {"in": 0, "out": 0}
        stats["trend"][k_trend]["in"] += 1
        
        # 结构统计 - 主播 (基于完成时间，代表产出)
        if v.host:
            for h in v.host.replace('，', ',').split(','):
                h = h.strip()
                if h: stats["hosts"][h] = stats["hosts"].get(h, 0) + 1

    # 3. 发布与分发统计 (基于发布时间)
    if dt_pub:
        if dt_pub >= windows["today"]: stats["flow"]["today_out"] += 1
        if dt_pub >= windows["month"]: stats["flow"]["month_out"] += 1
        
        # 趋势图 (Out)
        k_trend = _get_trend_key(dt_pub, dim)
        if k_trend not in stats["trend"]: stats["trend"][k_trend] = {"in": 0, "out": 0}
        stats["trend"][k_trend]["out"] += 1
        
        # 矩阵统计 (账号维度)
        if v.status == "已发布" and v.platform:
            accs = [p.strip() for p in v.platform.replace('，', ',').split(',') if p.strip()]
            for acc in accs:
                stats["dist_total"] += 1
                
                # 雷达图数据
                stats["plats"][acc] = stats["plats"].get(acc, 0) + 1
                
                # 矩阵表数据
                if acc not in stats["matrix"]: 
                    stats["matrix"][acc] = {"day": 0, "week": 0, "month": 0, "year": 0}
                
                mat = stats["matrix"][acc]
                if dt_pub >= windows["today"]: mat["day"] += 1
                if dt_pub >= windows["week"]: mat["week"] += 1
                if dt_pub >= windows["month"]: mat["month"] += 1
                if dt_pub >= windows["year"]: mat["year"] += 1

    # 4. 视频类型统计
    if v.video_type:
        stats["types"][v.video_type] = stats["types"].get(v.video_type, 0) + 1

def _get_trend_key(dt: datetime.datetime, dim: str) -> str:
    if dim == 'month': return dt.strftime("%Y-%m")
    if dim == 'week': return dt.strftime("%Y-W%W")
    return dt.strftime("%Y-%m-%d")

def _format_dashboard_response(stats: dict) -> dict:
    # 趋势图排序
    sorted_keys = sorted(stats["trend"].keys())[-30:] # 取最近30个点
    trend_data = {
        "dates": sorted_keys,
        "in": [stats["trend"][k]["in"] for k in sorted_keys],
        "out": [stats["trend"][k]["out"] for k in sorted_keys]
    }
    
    # 矩阵表排序 (按年产量倒序)
    matrix_list = [{"name": k, **v} for k, v in stats["matrix"].items()]
    matrix_list.sort(key=lambda x: x["year"], reverse=True)
    
    # 主播排行 (Top 10)
    host_list = sorted([{"name": k, "value": v} for k, v in stats["hosts"].items()], key=lambda x: x['value'], reverse=True)[:10]
    
    # 其他
    type_list = [{"name": k, "value": v} for k, v in stats["types"].items()]
    plat_list = [{"name": k, "value": v} for k, v in stats["plats"].items()]
    
    return {
        "kpi": {
            "total": stats["total"],
            "pending": stats["pending"],
            "dist_total": stats["dist_total"],
            "today_in": stats["flow"]["today_in"],
            "today_out": stats["flow"]["today_out"],
            "month_in": stats["flow"]["month_in"],
            "month_out": stats["flow"]["month_out"]
        },
        "trend": trend_data,
        "matrix": matrix_list,
        "hosts": host_list,
        "types": type_list,
        "plats": plat_list
    }

# ==========================================
# 4. 产品 SPU 统计接口
# ==========================================

@app.get("/api/product_stats")
def get_product_stats():
    with Session(engine) as session:
        videos = session.exec(select(Video.product_id, Video.status)).all()
        
        stats = {}
        for pid, status in videos:
            if not pid: pid = "未分类"
            pid = pid.strip()
            
            if pid not in stats:
                stats[pid] = {"name": pid, "total": 0, "pending": 0}
            
            stats[pid]["total"] += 1
            if status == "待发布":
                stats[pid]["pending"] += 1
        
        # 排序策略：待发布数量多的排前面，其次是总库存多的
        result = list(stats.values())
        result.sort(key=lambda x: (x["pending"], x["total"]), reverse=True)
        
        return result

# ==========================================
# 5. 视频列表与操作接口
# ==========================================

@app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, sort_by: str = "id", order: str = "desc",
    keyword: Optional[str] = None, 
    # 高级筛选字段
    host: Optional[str] = None, status: Optional[str] = None,
    category: Optional[str] = None, platform: Optional[str] = None, video_type: Optional[str] = None,
    product_id: Optional[str] = None, title: Optional[str] = None, remark: Optional[str] = None,
    finish_start: Optional[str] = None, finish_end: Optional[str] = None,
    publish_start: Optional[str] = None, publish_end: Optional[str] = None
):
    with Session(engine) as session:
        stmt = select(Video)
        
        # 全局模糊搜索
        if keyword:
            stmt = stmt.where(or_(
                col(Video.title).contains(keyword),
                col(Video.product_id).contains(keyword),
                col(Video.remark).contains(keyword)
            ))
        
        # 精确字段筛选
        if product_id: stmt = stmt.where(col(Video.product_id).contains(product_id))
        if title: stmt = stmt.where(col(Video.title).contains(title))
        if remark: stmt = stmt.where(col(Video.remark).contains(remark))
        
        # 下拉多选筛选
        if host and "全部" not in host: stmt = stmt.where(col(Video.host).contains(host))
        if platform and "全部" not in platform: stmt = stmt.where(col(Video.platform).contains(platform))
        if category and "全部" not in category: stmt = stmt.where(Video.category == category)
        if status and "全部" not in status: stmt = stmt.where(Video.status == status)
        if video_type and "全部" not in video_type: stmt = stmt.where(Video.video_type == video_type)
        
        # 时间范围筛选
        if finish_start: stmt = stmt.where(Video.finish_time >= finish_start)
        if finish_end: stmt = stmt.where(Video.finish_time <= finish_end)
        if publish_start: stmt = stmt.where(Video.publish_time >= publish_start)
        if publish_end: stmt = stmt.where(Video.publish_time <= publish_end)

        # 排序
        sort_col = getattr(Video, sort_by, Video.id)
        if order == "asc":
            stmt = stmt.order_by(asc(sort_col))
        else:
            stmt = stmt.order_by(desc(sort_col))
            
        # 分页
        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        stmt = stmt.offset((page - 1) * size).limit(size)
        results = session.exec(stmt).all()
        
        return {
            "items": results,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": math.ceil(total / size)
        }

@app.post("/api/video/save")
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
        # 判断新增还是编辑
        if not id or id in ['new', 'temp', 'undefined', 'null']:
            video = Video(
                product_id=product_id or "", 
                title=title or "", 
                image_url="/assets/default.png",
                created_at=datetime.datetime.now()
            )
            session.add(video)
            logger.info(f"新增视频: {title}")
        else:
            video = session.get(Video, int(id))
            if not video:
                raise HTTPException(status_code=404, detail="Item not found")
        
        # 更新字段
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
        return {"message": "Saved successfully", "id": video.id}

@app.delete("/api/video/{video_id}")
def delete_video(video_id: int):
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        session.delete(video)
        session.commit()
        logger.info(f"删除视频 ID: {video_id}")
    return {"message": "Deleted successfully"}

# ==========================================
# 6. 配置与上传接口
# ==========================================

@app.get("/api/options")
def get_options():
    with Session(engine) as session:
        settings = {item.key: item.value.split(',') for item in session.exec(select(AppSettings)).all()}
        
        def merge_options(col, key):
            # 获取数据库中现有的值
            db_vals = session.exec(select(col).distinct()).all()
            clean = []
            for item in db_vals:
                if item and str(item).lower() not in ['nan', 'none', '']:
                    # 支持逗号分隔的字段拆分
                    clean.extend([x.strip() for x in str(item).replace('，', ',').split(',')])
            # 获取后台配置的值
            preset = [x.strip() for x in settings.get(key, []) if x.strip()]
            # 合并去重并排序
            return sorted(list(set(clean + preset)))
            
        return {
            "hosts": merge_options(Video.host, "hosts"),
            "categories": merge_options(Video.category, "categories"),
            "statuses": merge_options(Video.status, "statuses"),
            "platforms": merge_options(Video.platform, "platforms"),
            "video_types": merge_options(Video.video_type, "video_types"),
            "product_ids": merge_options(Video.product_id, "ignore")
        }

@app.post("/api/settings")
def update_settings(key: str = Form(...), value: str = Form(...)):
    with Session(engine) as session:
        s = session.get(AppSettings, key)
        if not s:
            s = AppSettings(key=key, value=value)
        else:
            s.value = value
        session.add(s)
        session.commit()
    return {"message": "Settings updated"}

@app.post("/api/upload")
async def upload_image(file: UploadFile):
    os.makedirs("assets/previews", exist_ok=True)
    
    # 生成安全文件名
    ext = file.filename.split('.')[-1] if '.' in file.filename else "png"
    filename = f"upl_{uuid.uuid4().hex[:8]}.{ext}"
    file_path = f"assets/previews/{filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"url": f"/{file_path}"}

@app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    upload_dir = "temp_uploads"
    if not os.path.exists(upload_dir):
        raise HTTPException(404, "Upload directory not found")
        
    files = [f for f in os.listdir(upload_dir) if f.endswith(".xlsx") or f.endswith(".xls")]
    if not files:
        raise HTTPException(404, "No Excel files found in temp_uploads")
        
    # 取第一个 Excel 文件进行处理
    target_file = os.path.join(upload_dir, files[0])
    bg_tasks.add_task(process_excel_background, target_file, engine)
    
    return {"message": "Background import task started", "file": files[0]}