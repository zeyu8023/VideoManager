import os
import shutil
import math
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select, col, or_
from sqlalchemy import func
from typing import Optional, List

# 导入你之前的 processor (确保 backend/processor.py 存在)
from .processor import process_excel_background
# 导入模型 (确保 backend/models.py 存在)
from .models import Video

# === 初始化 App ===
main_app = FastAPI(title="VideoHub Backend")
engine = create_engine("sqlite:///data/inventory.db")

@main_app.on_event("startup")
def on_startup():
    # 确保目录存在
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    # 创建数据库表
    SQLModel.metadata.create_all(engine)

# 挂载静态资源 (图片)
main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# === 核心路由 ===

# 1. 首页：返回 index.html
@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# 2. 统计接口 (看板数据)
@main_app.get("/api/stats")
def get_stats():
    with Session(engine) as session:
        # 使用 func.count 提高性能
        total = session.exec(select(func.count(Video.id))).one()
        pending = session.exec(select(func.count(Video.id)).where(Video.status == "待发布")).one()
        
        # 简单逻辑：获取出现次数最多的主播 (生产环境可用更复杂的 group by)
        # 这里暂时返回静态或简单的
        return {
            "total": total,
            "pending": pending,
            "host": "小梨" # 这里的统计逻辑可根据需求复杂化
        }

# 3. 视频列表接口 (支持分页、搜索、筛选)
@main_app.get("/api/videos")
def list_videos(
    page: int = 1,
    size: int = 15,
    keyword: Optional[str] = None,
    status: Optional[str] = None
):
    with Session(engine) as session:
        # 构建基础查询
        statement = select(Video)

        # 关键词搜索 (同时搜标题、产品ID、主播)
        if keyword:
            statement = statement.where(
                or_(
                    col(Video.title).contains(keyword),
                    col(Video.product_id).contains(keyword),
                    col(Video.host).contains(keyword)
                )
            )
        
        # 状态筛选
        if status and status != "全部":
            statement = statement.where(Video.status == status)

        # 计算总条数 (用于前端计算页码)
        # 注意：先计算 count 再做 limit
        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        # 排序与分页
        statement = statement.order_by(Video.id.desc()).offset((page - 1) * size).limit(size)
        results = session.exec(statement).all()

        return {
            "items": results,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": math.ceil(total / size)
        }

# 4. 手动新增接口
@main_app.post("/api/video/add")
async def add_video(
    product_id: str = Form(...),
    title: str = Form(...),
    host: str = Form(...),
    status: str = Form(...),
    category: str = Form(...),
    platform: str = Form(""),
    image: UploadFile = None
):
    with Session(engine) as session:
        img_url = "/assets/default.png"
        if image:
            # 保存上传的图片
            ext = image.filename.split('.')[-1] if '.' in image.filename else "png"
            filename = f"manual_{product_id}_{title[:5]}.{ext}"
            img_path = os.path.join("assets", "previews", filename)
            
            with open(img_path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
            img_url = f"/assets/previews/{filename}"
            
        new_video = Video(
            product_id=product_id,
            title=title,
            host=host,
            status=status,
            category=category,
            platform=platform,
            image_url=img_url
        )
        session.add(new_video)
        session.commit()
        return {"message": "新增成功", "id": new_video.id}

# 5. 本地目录扫描接口 (400M 大文件处理)
@main_app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    # 扫描 temp_uploads 下的所有 xlsx
    if not os.path.exists("temp_uploads"):
        raise HTTPException(status_code=404, detail="目录不存在")
        
    files = [f for f in os.listdir("temp_uploads") if f.endswith(".xlsx")]
    if not files:
        raise HTTPException(status_code=404, detail="temp_uploads 目录为空，请先上传文件")
    
    # 取第一个文件处理
    target_file = os.path.join("temp_uploads", files[0])
    
    # 后台执行，立即返回
    bg_tasks.add_task(process_excel_background, target_file, engine)
    
    return {"message": f"已发现文件 {files[0]}，后台处理任务已启动"}