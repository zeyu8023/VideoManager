import os, pandas as pd
from openpyxl import load_workbook
from openpyxl_image_loader import SheetImageLoader
from sqlmodel import Session
from .models import Video

def process_excel_background(file_path: str, db_engine):
    print(f"开始处理: {file_path}")
    os.makedirs("assets/previews", exist_ok=True)
    
    # 1. 预处理 DataFrame，清洗 nan
    df = pd.read_excel(file_path)
    # 将 Pandas 的 NaN/NaT 全部替换为空字符串
    df = df.fillna('')
    # 将所有内容转为字符串，防止日期格式报错
    df = df.astype(str)
    # 再次清理可能产生的 'nan' 字符串
    df = df.replace('nan', '').replace('NaT', '')

    # 2. 图片加载器
    pxl = load_workbook(file_path, data_only=True)
    loader = SheetImageLoader(pxl.active)

    with Session(db_engine) as session:
        for index, row in df.iterrows():
            # 字段映射
            p_id = row.get('产品名称/编号', '').strip()
            title = row.get('视频标题', '').strip()
            
            # 图片提取
            img_path = f"assets/previews/{p_id}_{index}.png"
            final_url = "" # 默认为空，前端显示占位图
            
            try:
                # 假设图片在 C 列
                cell_ref = f"C{index+2}"
                if loader.image_in_cell(cell_ref):
                    loader.get(cell_ref).save(img_path)
                    final_url = f"/{img_path}"
            except:
                pass # 提取失败则为空

            video = Video(
                product_id=p_id, 
                title=title, 
                image_url=final_url,
                category=row.get('产品类型', ''),
                finish_time=row.get('完成时间', ''),
                video_type=row.get('视频类型', ''),
                host=row.get('主播', ''),
                status=row.get('当前状态', ''),
                platform=row.get('发布平台', ''),
                publish_time=row.get('发布时间', ''),
                remark=row.get('备注', '')
            )
            session.add(video)
        session.commit()
    
    os.remove(file_path)
    print("导入完成")