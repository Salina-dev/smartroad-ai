from db import Database

def main():
    db = Database('data/road_damage.db')
    try:
        db.initialize()
        if not db.get_user_by_email('interactive_test@example.com'):
            db.create_user('Interactive Test','interactive_test@example.com','000','Engineering','InteractivePass!')
        user = db.get_user_by_email('interactive_test@example.com')
        print('User found:', bool(user))
        if user:
            print(dict(user))
    except Exception as e:
        print('ERROR', e)

if __name__ == '__main__':
    main()
