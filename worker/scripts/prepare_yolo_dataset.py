import os
import cv2
import shutil
import glob
import random

def extract_frames(video_path: str, output_dir: str, interval_sec: float = 1.0):
    """비디오에서 지정된 간격(초)마다 프레임을 추출합니다."""
    if not os.path.exists(video_path):
        print(f"Error: Video file {video_path} not found.")
        return

    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = int(fps * interval_sec)
    
    count = 0
    saved_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        if count % frame_interval == 0:
            frame_name = f"frame_{saved_count:04d}.jpg"
            cv2.imwrite(os.path.join(output_dir, frame_name), frame)
            saved_count += 1
            
        count += 1
        
    cap.release()
    print(f"Extracted {saved_count} frames to {output_dir}")

def split_dataset(src_images_dir: str, src_labels_dir: str, dest_dir: str, split_ratio=(0.7, 0.2, 0.1)):
    """
    라벨링이 완료된 이미지와 txt 파일을 train/val/test 폴더로 분할합니다.
    """
    images = glob.glob(os.path.join(src_images_dir, "*.jpg")) + glob.glob(os.path.join(src_images_dir, "*.png"))
    
    # Filter only images that have corresponding label files
    valid_data = []
    for img_path in images:
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        label_path = os.path.join(src_labels_dir, f"{base_name}.txt")
        if os.path.exists(label_path):
            valid_data.append((img_path, label_path))
            
    if not valid_data:
        print("No labeled data found for splitting.")
        return
        
    random.seed(42)
    random.shuffle(valid_data)
    
    total = len(valid_data)
    train_end = int(total * split_ratio[0])
    val_end = train_end + int(total * split_ratio[1])
    
    splits = {
        "train": valid_data[:train_end],
        "val": valid_data[train_end:val_end],
        "test": valid_data[val_end:]
    }
    
    for split_name, data in splits.items():
        img_out = os.path.join(dest_dir, "images", split_name)
        lbl_out = os.path.join(dest_dir, "labels", split_name)
        os.makedirs(img_out, exist_ok=True)
        os.makedirs(lbl_out, exist_ok=True)
        
        for img_p, lbl_p in data:
            shutil.copy(img_p, os.path.join(img_out, os.path.basename(img_p)))
            shutil.copy(lbl_p, os.path.join(lbl_out, os.path.basename(lbl_p)))
            
        print(f"{split_name}: {len(data)} items")
        
    print(f"Dataset successfully split into {dest_dir}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", help="Path to video file")
    parser.add_argument("--unlabeled_dir", default="datasets/unlabeled", help="Dir to save extracted frames")
    parser.add_argument("--labeled_dir", help="Dir containing labeled images and txts to split")
    parser.add_argument("--dest_dir", default="datasets/book_spines", help="Final YOLO dataset dir")
    
    args = parser.parse_args()
    
    if args.video:
        print("1. Extracting frames...")
        extract_frames(args.video, args.unlabeled_dir)
        print(f"Please label the images in {args.unlabeled_dir} using a tool like LabelImg, and save YOLO .txt labels in the same directory or a separate labels directory.")
        
    if args.labeled_dir:
        print("2. Splitting dataset...")
        split_dataset(args.labeled_dir, args.labeled_dir, args.dest_dir)
