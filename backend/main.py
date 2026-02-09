from fastapi import FastAPI, UploadFile, BackgroundTasks, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, create_engine, SQLModel, select
from .models import Video, User
from .processor import process_excel_background
import os, shutil

main_app = FastAPI()
engine = create_engine("sqlite:///data/inventory.db")

# 挂载静态文件用于显示图片
os.makedirs("assets", exist_ok=True)
main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@main_app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

@main_app.get("/api/stats")
def get_stats():
    with Session(engine) as session:
        total = len(session.exec(select(Video)).all())
        pending = len(session.exec(select(Video).where(Video.status == "待发布")).all())
        return {"total": total, "pending": pending, "host": "小梨"}

@main_app.post("/api/import")
async def import_data(file: UploadFile, bg_tasks: BackgroundTasks):
    os.makedirs("temp_uploads", exist_ok=True)
    temp_path = f"temp_uploads/{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    bg_tasks.add_task(process_excel_background, temp_path, engine)
    return {"message": "后台处理中，请稍后刷新"}

@main_app.get("/api/videos")
def list_videos():
    with Session(engine) as session:
        return session.exec(select(Video)).all()