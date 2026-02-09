import os
import pandas as pd
from openpyxl import load_workbook
from openpyxl_image_loader import SheetImageLoader
from sqlmodel import Session, create_engine, SQLModel
# 注意：运行时需确保在 backend 目录下能引用 models
# 这里简化为独立逻辑

def extract_excel_data(file_path):
    print("正在解压巨无霸 Excel，请稍候...")
    pxl_doc = load_workbook(file_path)
    sheet = pxl_doc.active
    image_loader = SheetImageLoader(sheet)
    
    # 读取文字数据
    df = pd.read_excel(file_path)
    
    if not os.path.exists("assets/previews"):
        os.makedirs("assets/previews")

    # 遍历并保存图片
    for index, row in df.iterrows():
        # 假设图片在第 3 列 (C列)，Excel 从1开始算，索引可能需调整
        cell_loc = f"C{index + 2}" 
        try:
            image = image_loader.get(cell_loc)
            img_name = f"img_{index}.png"
            image.save(f"assets/previews/{img_name}")
            print(f"提取图片: {img_name}")
        except:
            continue

if __name__ == "__main__":
    # extract_excel_data("your_big_file.xlsx")
    pass