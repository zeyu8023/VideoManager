import os, shutil
from fastapi import FastAPI, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, create_engine, SQLModel, select
from .models import Video
from .processor import process_excel_background

main_app = FastAPI()
engine = create_engine("sqlite:///data/inventory.db")

# 初始化环境
@main_app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets/previews", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
    SQLModel.metadata.create_all(engine)

# 挂载静态资源
main_app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# --- 路由开始 ---

@main_app.get("/")
async def read_index():
    return FileResponse(os.path.join("frontend", "index.html"))

# 1. 统计接口
@main_app.get("/api/stats")
def get_stats():
    with Session(engine) as session:
        videos = session.exec(select(Video)).all()
        return {
            "total": len(videos),
            "pending": len([v for v in videos if v.status == "待发布"]),
            "host": "小梨"
        }

# 2. 列表接口
@main_app.get("/api/videos")
def list_videos():
    with Session(engine) as session:
        return session.exec(select(Video).order_by(Video.id.desc())).all()

# 3. 本地扫描导入接口 (手动把文件丢进 temp_uploads 后点击)
@main_app.post("/api/import/local")
async def import_local(bg_tasks: BackgroundTasks):
    files = [f for f in os.listdir("temp_uploads") if f.endswith(".xlsx")]
    if not files:
        raise HTTPException(status_code=404, detail="未在 temp_uploads 目录找到 .xlsx 文件")
    
    # 默认处理第一个找到的文件
    file_path = os.path.join("temp_uploads", files[0])
    bg_tasks.add_task(process_excel_background, file_path, engine)
    return {"message": f"已发现文件 {files[0]}，后台脱水任务已启动"}

# 4. 手动新增接口
@main_app.post("/api/video/add")
async def add_video(
    product_id: str = Form(...), title: str = Form(...),
    host: str = Form(...), status: str = Form(...),
    category: str = Form(...), platform: str = Form(""),
    image: UploadFile = None
):
    with Session(engine) as session:
        img_url = "/assets/default.png"
        if image:
            img_path = f"assets/previews/manual_{product_id}.png"
            with open(img_path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
            img_url = f"/{img_path}"
            
        new_v = Video(
            product_id=product_id, title=title, host=host,
            status=status, category=category, image_url=img_url,
            platform=platform
        )
        session.add(new_v)
        session.commit()
    return {"message": "新增成功"}