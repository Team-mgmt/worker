import cv2
import numpy as np

def enhance_contrast(img_bgr: np.ndarray) -> np.ndarray:
    """Apply CLAHE to enhance contrast."""
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    cl = clahe.apply(l_channel)
    limg = cv2.merge((cl, a, b))
    enhanced_img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
    return enhanced_img

def extract_label_from_spine(spine_bgr: np.ndarray) -> np.ndarray:
    """
    Robust baseline label extraction:
    1. Crops the bottom part of the spine where the label is located.
    2. Upscales the image to help OCR recognize small numbers.
    3. Enhances contrast.
    """
    h, w = spine_bgr.shape[:2]
    
    # Label is usually in the bottom 30% of the spine
    crop_h = int(h * 0.3)
    if crop_h > 150: # Cap it if image is too large
        crop_h = 150
        
    label_img = spine_bgr[h - crop_h:h, :]
    
    # Upscale 2x to make characters larger for OCR
    label_img = cv2.resize(label_img, (w * 2, crop_h * 2), interpolation=cv2.INTER_CUBIC)
    
    # Enhance contrast
    label_img = enhance_contrast(label_img)
    
    return label_img
