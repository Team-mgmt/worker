import json
import os
import cv2

def convert_to_yolo():
    json_path = "worker/tests/bboxes.json"
    images_dir = "worker/tests/test_images"
    
    out_images_dir = "worker/datasets/book_spines/images/train"
    out_labels_dir = "worker/datasets/book_spines/labels/train"
    os.makedirs(out_images_dir, exist_ok=True)
    os.makedirs(out_labels_dir, exist_ok=True)
    
    # Also create val split with the same images just for dummy validation
    val_images_dir = "worker/datasets/book_spines/images/val"
    val_labels_dir = "worker/datasets/book_spines/labels/val"
    os.makedirs(val_images_dir, exist_ok=True)
    os.makedirs(val_labels_dir, exist_ok=True)
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    for filename, boxes in data.items():
        img_path = os.path.join(images_dir, filename)
        if not os.path.exists(img_path):
            continue
            
        img = cv2.imread(img_path)
        h, w = img.shape[:2]
        
        # Save images
        cv2.imwrite(os.path.join(out_images_dir, filename), img)
        cv2.imwrite(os.path.join(val_images_dir, filename), img)
        
        # Create YOLO label
        base_name = os.path.splitext(filename)[0]
        label_content = ""
        for b in boxes:
            x, y, bw, bh = b["bbox"]
            # YOLO format: class x_center y_center width height (normalized)
            xc = (x + bw / 2) / w
            yc = (y + bh / 2) / h
            nw = bw / w
            nh = bh / h
            label_content += f"0 {xc} {yc} {nw} {nh}\n"
            
        with open(os.path.join(out_labels_dir, f"{base_name}.txt"), "w") as f:
            f.write(label_content)
        with open(os.path.join(val_labels_dir, f"{base_name}.txt"), "w") as f:
            f.write(label_content)
            
    print("Prepared YOLO dataset for E2E testing using the 2 demo images.")

if __name__ == "__main__":
    convert_to_yolo()
