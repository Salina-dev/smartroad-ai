from detector import RoadDamageDetector
import cv2
from pathlib import Path

out_dir = Path('uploads')
out_dir.mkdir(exist_ok=True)
img_path = out_dir / 'dummy.jpg'
# create a small blank image
import numpy as np
img = np.zeros((480,640,3), dtype=np.uint8)
cv2.imwrite(str(img_path), img)

det = RoadDamageDetector()
print('Model ready:', det.is_ready)
detections = det.detect_image(str(img_path))
print('Detections:', detections)
