import os

os.environ["USERPROFILE"] = r"C:\dev\paddle_models"
os.environ["HOMEDRIVE"] = "C:"
os.environ["HOMEPATH"] = r"\dev\paddle_models"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_mkldnn_bfloat16"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"

import cv2
import numpy as np
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=True, lang='korean', show_log=False, use_mkldnn=False)

def process(img_path, out_path):
    img_array = np.fromfile(img_path, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    result = ocr.ocr(img, cls=True)
    
    if result and result[0]:
        for line in result[0]:
            box = line[0]
            text = line[1][0]
            pts = np.array(box, np.int32).reshape((-1, 1, 2))
            cv2.polylines(img, [pts], True, (0, 0, 255), 2)
            # Add text
            cv2.putText(img, text, (int(box[0][0]), int(box[0][1]) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            print(f"[{text}] box: {box}")
            
    # Save the result
    is_success, im_buf_arr = cv2.imencode('.png', img)
    if is_success:
        im_buf_arr.tofile(out_path)

if __name__ == '__main__':
    print("Processing image 1...")
    process(r'C:\dev\comp_lib\worker\worker\tests\test_images\nowon_shelf_real_001.jpg', r'C:\dev\comp_lib\worker\worker\tests\test_images\nowon_shelf_real_001_ocr.png')
    print("Processing image 2...")
    process(r'C:\dev\comp_lib\worker\worker\tests\test_images\nowon_shelf_real_002.jpg', r'C:\dev\comp_lib\worker\worker\tests\test_images\nowon_shelf_real_002_ocr.png')
