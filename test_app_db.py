from db import Database
import json

DB_PATH = 'smartroad.db'

def main():
    db = Database(DB_PATH)
    db.initialize()

    email = 'app_test_user@example.com'
    user = db.get_user_by_email(email)
    if not user:
        db.create_user('App Test User', email, '1234567890', 'QA', 'AppTestPass!')
        user = db.get_user_by_email(email)

    print('User exists:', bool(user))
    print('Email:', user['email'])

    verified = db.verify_password('AppTestPass!', user['password_hash'])
    print('Password verified:', verified)

    # Add a sample detection record using the real app DB schema
    db.add_detection_record(
        user_id=user['id'],
        filename='uploads/sample_test_image.jpg',
        media_type='image',
        location_country='TestLand',
        location_state='TestState',
        location_city='TestCity',
        location_area='TestArea',
        location_road_name='Test Road',
        latitude='12.3456',
        longitude='65.4321',
        total_potholes=0,
        total_cracks=0,
        critical_damages=0,
        average_confidence=0.0,
        condition_score=100,
        detections_json=json.dumps([]),
    )

    records = db.get_detection_history(user['id'])
    print('History records count:', len(records))
    for record in records[-3:]:
        print(dict(record))

if __name__ == '__main__':
    main()
