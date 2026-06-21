from pathlib import Path
import urllib.request
import cv2
import numpy as np
from detector import RoadDamageDetector

uploads = Path('uploads')
uploads.mkdir(exist_ok=True)

sample_urls = [
    'https://raw.githubusercontent.com/oracl4/RoadDamageDetection/main/resource/RDD_Image_Example.gif',
    'https://raw.githubusercontent.com/oracl4/RoadDamageDetection/main/resource/RDD_Video_Example.gif',
]

model = RoadDamageDetector(model_path='models/best.pt')
print('detector ready:', model.is_ready)
print('class names:', model.class_names)

for i, url in enumerate(sample_urls, start=1):
    target = uploads / f'sample_{i}.gif'
    print('Downloading', url)
    try:
        urllib.request.urlretrieve(url, target)
        print('Saved', target)
    except Exception as e:
        print('Download failed for', url, e)
        continue

    img = cv2.imread(str(target))
    if img is None:
        print('Cannot read image', target)
        continue
    detections = model.detect_frame(img)
    print(target.name, 'detections count:', len(detections))
    for d in detections:
        print(d)

    out = uploads / f'res_{i}.jpg'
    for item in detections:
        x1, y1, x2, y2 = item['bbox']
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 160, 255), 2)
        label = f"{item['label']} {item['severity']} {item['confidence']*100:.1f}%"
        cv2.putText(img, label, (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
    cv2.imwrite(str(out), img)
    print('Saved annotated output', out)
