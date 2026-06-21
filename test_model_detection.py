from detector import RoadDamageDetector
from pathlib import Path
import cv2
import numpy as np

uploads = Path('uploads')
uploads.mkdir(exist_ok=True)
image_path = uploads / 'smoke_test.jpg'
if not image_path.exists():
    img = np.full((720, 1280, 3), 205, dtype=np.uint8)
    cv2.putText(img, 'ROAD PATCH', (200, 360), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 8)
    cv2.imwrite(str(image_path), img)

print('model file exists:', Path('models/best.pt').exists())
det = RoadDamageDetector(model_path='models/best.pt')
print('detector ready:', det.is_ready)
print('class names:', det.class_names)
detections = det.detect_image(image_path)
print('detections count:', len(detections))
for d in detections:
    print(d)
