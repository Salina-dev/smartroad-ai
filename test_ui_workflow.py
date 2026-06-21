import json
from pathlib import Path
import cv2
from db import Database
from detector import RoadDamageDetector
from report_generator import ReportGenerator

WORKSPACE = Path('.')
UPLOADS = WORKSPACE / 'uploads'
REPORTS = WORKSPACE / 'reports'
DB_PATH = WORKSPACE / 'smartroad.db'
SAMPLE_IMAGE = UPLOADS / 'sample_2.gif'

UPLOADS.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

# Ensure sample image exists
if not SAMPLE_IMAGE.exists():
    import urllib.request
    url = 'https://raw.githubusercontent.com/oracl4/RoadDamageDetection/main/resource/RDD_Video_Example.gif'
    urllib.request.urlretrieve(url, SAMPLE_IMAGE)
    print('Downloaded sample image to', SAMPLE_IMAGE)

# Load detector
model = RoadDamageDetector(model_path='models/best.pt')
print('Detector ready:', model.is_ready)
print('Model class names:', model.class_names)

# Read sample as image
image = cv2.imread(str(SAMPLE_IMAGE))
if image is None:
    raise SystemExit('Failed to read sample image')

# Run detection
records = model.detect_frame(image)
print('Detections found:', len(records))
for item in records:
    print(item)

if not records:
    raise SystemExit('No detections found -- workflow cannot continue')

# Save detection record to DB

db = Database(DB_PATH)
db.initialize()
user = db.get_user_by_email('app_test_user@example.com')
if user is None:
    raise SystemExit('Test user not found in DB')

location = {
    'country': 'SampleLand',
    'state': 'SampleState',
    'city': 'SampleCity',
    'area': 'SampleArea',
    'road_name': 'Sample Road',
    'latitude': '12.3456',
    'longitude': '65.4321',
}

potholes = sum(1 for d in records if d['label'] == 'Pothole')
cracks = sum(1 for d in records if 'Crack' in d['label'])
critical = sum(1 for d in records if d['severity'] == 'Critical')
avg_conf = round(sum(d['confidence'] for d in records) / len(records), 3)
condition_score = db.estimate_condition_score(records)

record_id = None
try:
    db.add_detection_record(
        user_id=user['id'],
        filename=str(SAMPLE_IMAGE.resolve()),
        media_type='image',
        location_country=location['country'],
        location_state=location['state'],
        location_city=location['city'],
        location_area=location['area'],
        location_road_name=location['road_name'],
        latitude=location['latitude'],
        longitude=location['longitude'],
        total_potholes=potholes,
        total_cracks=cracks,
        critical_damages=critical,
        average_confidence=avg_conf,
        condition_score=condition_score,
        detections_json=json.dumps(records),
    )
    print('Saved detection record to DB')
except Exception as e:
    raise SystemExit('DB save failed: ' + str(e))

# Retrieve latest record and generate reports
latest = db.get_detection_history(user['id'])[0]
print('Latest saved record ID:', latest['id'])
print('Latest detections JSON:', latest['detections_json'])

meta = {
    'user_name': user['full_name'],
    'inspection_date': latest['created_at'],
    'location': location,
    'file_name': Path(latest['filename']).name,
    'total_potholes': latest['total_potholes'],
    'total_cracks': latest['total_cracks'],
    'critical_damages': latest['critical_damages'],
    'condition_score': latest['condition_score'],
    'detections': json.loads(latest['detections_json']),
}

pdf_path = REPORTS / f'test_report_{latest["id"]}.pdf'
excel_path = REPORTS / f'test_report_{latest["id"]}.xlsx'
reporter = ReportGenerator()
reporter.generate_pdf_report(meta, pdf_path)
reporter.generate_excel_report(meta, excel_path)
print('Generated report files:', pdf_path, excel_path)
