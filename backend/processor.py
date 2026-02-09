import os, pandas as pd
from openpyxl import load_workbook
from openpyxl_image_loader import SheetImageLoader
from sqlmodel import Session
from .models import Video

def process_excel_background(file_path: str, db_engine):
    print(f"开始处理: {file_path}")
    os.makedirs("assets/previews", exist_ok=True)
    
    # 注意：这里假设你的 Excel 还是原来那个，如果列名变了，这里要微调
    pxl = load_workbook(file_path, data_only=True)
    loader = SheetImageLoader(pxl.active)
    df = pd.read_excel(file_path)

    with Session(db_engine) as session:
        for index, row in df.iterrows():
            # 字段映射 (根据你的图4 Excel 表头)
            p_id = str(row.get('产品名称/编号', ''))
            title = str(row.get('视频标题', ''))
            # 图片在 C 列 -> C2, C3...
            img_path = f"assets/previews/{p_id}_{index}.png"
            try:
                if loader.image_in_cell(f"C{index+2}"):
                    loader.get(f"C{index+2}").save(img_path)
                    url = f"/{img_path}"
                else: url = "/assets/default.png"
            except: url = "/assets/default.png"

            video = Video(
                product_id=p_id, title=title, image_url=url,
                category=str(row.get('产品类型', '')),
                finish_time=str(row.get('完成时间', '')),
                video_type=str(row.get('视频类型', '')),
                host=str(row.get('主播', '')),
                status=str(row.get('当前状态', '')),
                platform=str(row.get('发布平台', '')),
                publish_time=str(row.get('发布时间', '')),
                remark=str(row.get('备注', ''))
            )
            session.add(video)
        session.commit()
    os.remove(file_path)
    print("导入完成")