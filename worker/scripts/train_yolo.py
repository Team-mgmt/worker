import os
from ultralytics import YOLO

def train():
    print("Starting YOLOv8 fine-tuning for Book Spine Detection...")
    
    # Load pre-trained model
    model = YOLO("yolov8n.pt")
    
    # Train the model with early stopping based on validation mAP
    # patience=10 means it will stop if no improvement for 10 epochs
    results = model.train(
        data=os.path.abspath("worker/datasets/book_spines.yaml"),
        epochs=10,       # Fast training for demo
        patience=10,     # Early stopping patience
        batch=16,
        imgsz=640,
        project="worker/models",
        name="book_spine_run",
        exist_ok=True,
        save=True
    )
    
    print("\n--- Training Completed ---")
    
    # Report metrics
    val_results = model.val()
    
    # Get precision, recall, mAP50
    metrics = val_results.results_dict
    
    print("=== Validation Metrics ===")
    print(f"Precision: {metrics.get('metrics/precision(B)', 0):.4f}")
    print(f"Recall:    {metrics.get('metrics/recall(B)', 0):.4f}")
    print(f"mAP50:     {metrics.get('metrics/mAP50(B)', 0):.4f}")
    print(f"mAP50-95:  {metrics.get('metrics/mAP50-95(B)', 0):.4f}")
    
    print("\nModel saved to: worker/models/book_spine_run/weights/best.pt")

if __name__ == "__main__":
    train()
