import os
import pandas as pd
from openpyxl import load_workbook
from openpyxl_image_loader import SheetImageLoader
from sqlmodel import Session
from .models import Video

def process_excel_background(file_path: str, db_engine):
    print(f"开始脱水处理: {file_path}")
    img_save_dir = "assets/previews"
    os.makedirs(img_save_dir, exist_ok=True)

    # 优化内存读取：仅读取必要列
    pxl_doc = load_workbook(file_path, data_only=True)
    sheet = pxl_doc.active
    image_loader = SheetImageLoader(sheet)
    df = pd.read_excel(file_path)

    with Session(db_engine) as session:
        for index, row in df.iterrows():
            p_id = str(row.get('产品名称/编号', f'ID_{index}'))
            cell_loc = f"C{index + 2}" # 假设图片在C列
            img_name = f"{p_id}_{index}.png"
            img_path = f"{img_save_dir}/{img_name}"

            try:
                if image_loader.image_in_cell(cell_loc):
                    image = image_loader.get(cell_loc)
                    image.save(img_path)
                    final_url = f"/assets/previews/{img_name}"
                else:
                    final_url = "/assets/default.png"
            except:
                final_url = "/assets/default.png"

            video = Video(
                product_id=p_id,
                title=str(row.get('视频标题', '无标题')),
                host=str(row.get('主播', 'VIVI')),
                status=str(row.get('当前状态', '待发布')),
                category=str(row.get('产品类型', '球服')),
                finish_time=str(row.get('完成时间', '')),
                image_url=final_url,
                platform=str(row.get('发布平台', ''))
            )
            session.add(video)
        session.commit()
    os.remove(file_path)
    print("处理完成，临时文件已清理")