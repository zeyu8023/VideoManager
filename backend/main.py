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

main_app = FastAPI(title="VideoHub V22.0 Ultimate Edition")
engine = create_engine("sqlite:///data/inventory.db")

# ==========================================
# 工具函数：日期解析与处理
# ==========================================
def parse_safe_date(date_str):
    """
    强力日期解析函数
    能处理: '2023-01-01', '2023/01/01', '20230101', 以及带时间的情况
    """
    if not date_str or str(date_str).lower() in ['nan', 'none', '', 'nat', 'null']:
        return None
    try:
        # 截取前10位处理 YYYY-MM-DD
        date_str = str(date_str).strip()[:10]
        # 尝试多种格式
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
            try:
                return datetime.datetime.strptime(date_str, fmt)
            except:
                continue
    except:
        return None
    return None

# ==========================================
# 系统初始化
# ==========================================
@main_app.on_event("startup")
def on_startup():
    # 1. 创建必要目录
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    
    # 2. 初始化数据库表结构
    SQLModel.metadata.create_all(engine)
    
    # 3. 数据库结构自动迁移 (Auto Migration)
    with Session(engine) as session:
        # 检查是否需要添加 created_at 字段
        try:
            session.exec(text("SELECT created_at FROM video LIMIT 1"))
        except Exception: 
            print("Detecting schema change: adding created_at column...")
            try: 
                session.exec(text("ALTER TABLE video ADD COLUMN created_at DATETIME"))
                session.commit()
            except Exception as e: 
                print(f"Migration warning: {e}")
        
        # 4. 数据清洗：给旧数据补全时间
        # 如果 created_at 为空，先尝试用 finish_time 填充，实在不行用当前时间
        session.exec(text("UPDATE video SET created_at = finish_time WHERE created_at IS NULL AND finish_time IS NOT NULL"))
        session.exec(text(f"UPDATE video SET created_at = '{datetime.datetime.now()}' WHERE created_at IS NULL"))
        session.commit()

        # 5. 初始化默认全局配置 (防止下拉框为空)
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
        session.commit()

main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# ==========================================
# 核心接口 1：全能仪表盘数据 (聚合计算)
# ==========================================
@main_app.get("/api/dashboard")
def get_dashboard_data(dim: str = "day"):
    """
    Dashboard 核心聚合接口
    返回：KPI、趋势图、账号矩阵、主播排行、类型占比、平台分布
    """
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        
        # --- 1. 基础 KPI 指标 ---
        total_assets = len(videos)
        pending_count = sum(1 for v in videos if v.status == "待发布")
        
        # --- 2. 时间窗口定义 ---
        now = datetime.datetime.now()
        # 今日 0点
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 本周一 0点
        week_start = today_start - datetime.timedelta(days=now.weekday())
        # 本月1号 0点
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 今年1月1号 0点
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # --- 3. 统计容器初始化 ---
        # 流量统计
        flow_stats = {
            "today_in": 0, "today_out": 0,
            "month_in": 0, "month_out": 0
        }
        # 趋势图数据 {date_str: {in:0, out:0}}
        trend_map = {} 
        # 结构分布
        host_map = {}
        type_map = {}
        # 平台分发统计 (用于雷达图)
        plat_dist_map = {} 
        # 账号矩阵统计 {account_name: {day, week, month, year}}
        matrix_map = {}
        # 累计分发人次 (Total Distribution)
        total_distribution_count = 0 

        # --- 4. 遍历计算 ---
        for v in videos:
            dt_finish = parse_safe_date(v.finish_time)
            dt_publish = parse_safe_date(v.publish_time)
            
            # === A. 入库统计 (基于完成时间) ===
            if dt_finish:
                d_str = dt_finish.strftime("%Y-%m-%d")
                m_str = dt_finish.strftime("%Y-%m")
                
                # KPI 累加
                if dt_finish >= today_start: flow_stats["today_in"] += 1
                if dt_finish >= month_start: flow_stats["month_in"] += 1
                
                # 趋势图 Key 计算
                k_trend = d_str
                if dim == 'month': k_trend = m_str
                elif dim == 'week': k_trend = dt_finish.strftime("%Y-W%W")
                
                if k_trend not in trend_map: trend_map[k_trend] = {"in": 0, "out": 0}
                trend_map[k_trend]["in"] += 1

            # === B. 发布与分发统计 (基于发布时间) ===
            if dt_publish:
                d_str = dt_publish.strftime("%Y-%m-%d")
                m_str = dt_publish.strftime("%Y-%m")
                
                # KPI 累加
                if dt_publish >= today_start: flow_stats["today_out"] += 1
                if dt_publish >= month_start: flow_stats["month_out"] += 1
                
                # 趋势图 Key 计算
                k_trend = d_str
                if dim == 'month': k_trend = m_str
                elif dim == 'week': k_trend = dt_publish.strftime("%Y-W%W")
                
                if k_trend not in trend_map: trend_map[k_trend] = {"in": 0, "out": 0}
                trend_map[k_trend]["out"] += 1
                
                # === C. 矩阵账号统计 (核心逻辑) ===
                # 只有“已发布”且有时间的才算有效分发
                if v.status == "已发布" and v.platform:
                    # 拆分多选平台 (例如 "抖音, 小红书")
                    accounts = [p.strip() for p in v.platform.replace('，', ',').split(',') if p.strip()]
                    
                    for acc in accounts:
                        total_distribution_count += 1
                        
                        # 初始化账号数据结构
                        if acc not in matrix_map: 
                            matrix_map[acc] = {"day": 0, "week": 0, "month": 0, "year": 0}
                        
                        # 多维度累加
                        if dt_publish >= today_start: matrix_map[acc]["day"] += 1
                        if dt_publish >= week_start: matrix_map[acc]["week"] += 1
                        if dt_publish >= month_start: matrix_map[acc]["month"] += 1
                        if dt_publish >= year_start: matrix_map[acc]["year"] += 1
                        
                        # 雷达图数据累加
                        plat_dist_map[acc] = plat_dist_map.get(acc, 0) + 1

            # === D. 结构统计 ===
            # 主播产出 (只要拍完了就算产出，基于 finish_time)
            if v.host and dt_finish:
                for h in v.host.replace('，', ',').split(','):
                    h = h.strip()
                    if h: host_map[h] = host_map.get(h, 0) + 1
            
            # 内容类型分布
            if v.video_type:
                type_map[v.video_type] = type_map.get(v.video_type, 0) + 1

        # --- 5. 数据格式化与排序 ---
        
        # 趋势图：按日期排序，取最近 30 个周期
        sorted_keys = sorted(trend_map.keys())[-30:]
        
        # 矩阵列表：按年度发布量倒序排列
        matrix_list = [{"name": k, **v} for k, v in matrix_map.items()]
        matrix_list.sort(key=lambda x: x["year"], reverse=True)
        
        # 主播排行：取 Top 5
        sorted_hosts = sorted([{"name": k, "value": v} for k, v in host_map.items()], key=lambda x: x['value'], reverse=True)[:5]

        # 类型分布
        sorted_types = [{"name": k, "value": v} for k, v in type_map.items()]
        
        # 平台分布
        sorted_plats = [{"name": k, "value": v} for k, v in plat_dist_map.items()]

        return {
            "kpi": {
                "total": total_assets, 
                "pending": pending_count,
                "dist_total": total_distribution_count, # 累计分发人次
                "today_in": flow_stats["today_in"],
                "today_out": flow_stats["today_out"],
                "month_in": flow_stats["month_in"],
                "month_out": flow_stats["month_out"]
            },
            "trend": {
                "dates": sorted_keys,
                "in": [trend_map[k]["in"] for k in sorted_keys],
                "out": [trend_map[k]["out"] for k in sorted_keys]
            },
            "matrix": matrix_list,
            "hosts": sorted_hosts,
            "types": sorted_types,
            "plats": sorted_plats
        }

# ==========================================
# 核心 2：产品库存统计接口 (SPU维度)
# ==========================================
@main_app.get("/api/product_stats")
def get_product_stats():
    with Session(engine) as session:
        # 只查需要的字段，提高性能
        videos = session.exec(select(Video.product_id, Video.status)).all()
        
        stats = {} # {product_id: {name, total, pending}}
        
        for pid, status in videos:
            if not pid: pid = "未分类"
            pid = pid.strip()
            
            if pid not in stats:
                stats[pid] = {"name": pid, "total": 0, "pending": 0}
            
            stats[pid]["total"] += 1
            if status == "待发布":
                stats[pid]["pending"] += 1
        
        # 排序：优先处理积压多的(pending desc)，其次看总库存多的(total desc)
        result = list(stats.values())
        result.sort(key=lambda x: (x["pending"], x["total"]), reverse=True)
        
        return result

# ==========================================
# 核心 3：全字段筛选列表接口
# ==========================================
@main_app.get("/api/videos")
def list_videos(
    page: int = 1, size: int = 100, sort_by: str = "id", order: str = "desc",
    keyword: Optional[str] = None, 
    # 下拉筛选 (支持多选模糊匹配)
    host: Optional[str] = None, status: Optional[str] = None,
    category: Optional[str] = None, platform: Optional[str] = None, video_type: Optional[str] = None,
    # 文本筛选 (精确或模糊)
    product_id: Optional[str] = None, title: Optional[str] = None, remark: Optional[str] = None,
    # 时间范围筛选
    finish_start: Optional[str] = None, finish_end: Optional[str] = None,
    publish_start: Optional[str] = None, publish_end: Optional[str] = None
):
    with Session(engine) as session:
        stmt = select(Video)
        
        # 1. 综合搜索 (Or 条件)
        if keyword:
            stmt = stmt.where(or_(
                col(Video.title).contains(keyword),
                col(Video.product_id).contains(keyword),
                col(Video.remark).contains(keyword)
            ))
        
        # 2. 精确字段筛选
        if product_id: stmt = stmt.where(col(Video.product_id).contains(product_id))
        if title: stmt = stmt.where(col(Video.title).contains(title))
        if remark: stmt = stmt.where(col(Video.remark).contains(remark))
        
        # 3. 下拉框筛选 (支持多选包含逻辑, 过滤 "全部xxx")
        if host and "全部" not in host: stmt = stmt.where(col(Video.host).contains(host))
        if platform and "全部" not in platform: stmt = stmt.where(col(Video.platform).contains(platform))
        if category and "全部" not in category: stmt = stmt.where(Video.category == category)
        if status and "全部" not in status: stmt = stmt.where(Video.status == status)
        if video_type and "全部" not in video_type: stmt = stmt.where(Video.video_type == video_type)
        
        # 4. 时间范围筛选 (字符串字典序比较)
        if finish_start: stmt = stmt.where(Video.finish_time >= finish_start)
        if finish_end: stmt = stmt.where(Video.finish_time <= finish_end)
        if publish_start: stmt = stmt.where(Video.publish_time >= publish_start)
        if publish_end: stmt = stmt.where(Video.publish_time <= publish_end)

        # 5. 排序与分页
        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
        
        sort_col = getattr(Video, sort_by, Video.id)
        stmt = stmt.order_by(asc(sort_col) if order == "asc" else desc(sort_col))
        
        stmt = stmt.offset((page - 1) * size).limit(size)
        results = session.exec(stmt).all()
        
        return {
            "items": results,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": math.ceil(total / size)
        }

# ==========================================
# 4. 数据操作接口 (CRUD)
# ==========================================
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
        # 新增逻辑
        if not id or id in ['new', 'temp', 'undefined', 'null']:
            video = Video(
                product_id=product_id or "", 
                title=title or "", 
                image_url="/assets/default.png",
                created_at=datetime.datetime.now()
            )
            session.add(video)
        else:
            # 编辑逻辑
            video = session.get(Video, int(id))
            if not video: raise HTTPException(404, "Not found")
        
        # 字段更新 (允许更新为空字符串，实现清空功能)
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
    return {"message": "Updated"}

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
    return {"message": "Started"}