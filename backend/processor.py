import os, pandas as pd
from openpyxl import load_workbook
from openpyxl_image_loader import SheetImageLoader
from sqlmodel import Session
from .models import Video

def process_excel_background(file_path: str, db_engine):
    print(f"执行任务: {file_path}")
    os.makedirs("assets/previews", exist_ok=True)
    
    # 使用只读模式加载大文件
    pxl_doc = load_workbook(file_path, read_only=False, data_only=True)
    sheet = pxl_doc.active
    image_loader = SheetImageLoader(sheet)
    df = pd.read_excel(file_path)

    with Session(db_engine) as session:
        for index, row in df.iterrows():
            p_id = str(row.get('产品名称/编号', f'ID_{index}'))
            cell_loc = f"C{index + 2}" # 假设图片在C列
            img_path = f"assets/previews/{p_id}_{index}.png"

            try:
                if image_loader.image_in_cell(cell_loc):
                    image = image_loader.get(cell_loc)
                    image.save(img_path)
                    final_url = f"/{img_path}"
                else:
                    final_url = "/assets/default.png"
            except:
                final_url = "/assets/default.png"

            video = Video(
                product_id=p_id, title=str(row.get('视频标题', '无标题')),
                host=str(row.get('主播', 'VIVI')), status=str(row.get('当前状态', '待发布')),
                category=str(row.get('产品类型', '球服')), image_url=final_url,
                platform=str(row.get('发布平台', ''))
            )
            session.add(video)
        session.commit()
    os.remove(file_path)
    print("后台处理完成")