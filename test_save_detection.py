import json
from pathlib import Path
from db import Database

DB_PATH = Path('smartroad.db')
db = Database(DB_PATH)
db.initialize()

user = db.get_user_by_email('app_test_user@example.com')
if not user:
    raise SystemExit('Test app user not found')

sample_detections = [
    {'label': 'Pothole', 'confidence': 0.6530718207359314, 'severity': 'Critical', 'bbox': [733, 578, 1436, 638]},
    {'label': 'Pothole', 'confidence': 0.5079226493835449, 'severity': 'Medium', 'bbox': [1321, 389, 1419, 413]},
]

db.add_detection_record(
    user_id=user['id'],
    filename=str(Path('uploads/sample_2.gif').resolve()),
    media_type='image',
    location_country='TestLand',
    location_state='TestState',
    location_city='TestCity',
    location_area='TestArea',
    location_road_name='Test Road',
    latitude='12.3456',
    longitude='65.4321',
    total_potholes=sum(1 for d in sample_detections if d['label'] == 'Pothole'),
    total_cracks=0,
    critical_damages=sum(1 for d in sample_detections if d['severity'] == 'Critical'),
    average_confidence=round(sum(d['confidence'] for d in sample_detections) / len(sample_detections), 3),
    condition_score=db.estimate_condition_score(sample_detections),
    detections_json=json.dumps(sample_detections),
)

records = db.get_detection_history(user['id'])
print('history_count', len(records))
for rec in records[-2:]:
    print(dict(rec))
