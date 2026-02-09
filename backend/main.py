from fastapi import FastAPI, UploadFile, BackgroundTasks, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse  # 新增：用于返回 HTML 文件
from sqlmodel import Session, create_engine, SQLModel, select
from .models import Video, User
from .processor import process_excel_background
import os, shutil

main_app = FastAPI()
engine = create_engine("sqlite:///data/inventory.db")

# 1. 自动创建数据库和目录
@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)

# 2. 挂载静态资源（图片等）
main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# --- 新增：挂载前端页面 ---

# 优先处理 API 路由
@main_app.get("/api/stats")
def get_stats():
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        total = len(videos)
        pending = len([v for v in videos if v.status == "待发布"])
        return {"total": total, "pending": pending, "host": "小梨"}

@main_app.post("/api/import")
async def import_data(file: UploadFile, bg_tasks: BackgroundTasks):
    temp_path = f"temp_uploads/{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    bg_tasks.add_task(process_excel_background, temp_path, engine)
    return {"message": "后台处理中，请稍后刷新"}

@main_app.get("/api/videos")
def list_videos():
    with Session(engine) as session:
        return session.exec(select(Video)).all()

# 3. 最后处理根路径：返回 index.html
@main_app.get("/")
async def read_index():
    # 确保路径指向你在 Dockerfile 中复制 index.html 的位置
    index_path = os.path.join("frontend", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "前端文件未找到，请检查 Dockerfile 复制路径"}