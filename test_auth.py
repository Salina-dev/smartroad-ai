import os
from db import Database, hash_password, verify_password

DB = 'test_auth.db'
if os.path.exists(DB):
    os.remove(DB)

db = Database(DB)
db.initialize()

long_pw = 'p' * 300
short_pw = 'correcthorsebatterystaple'

print('Creating user with long password...')
db.create_user('Long User', 'long@example.com', '123', 'Dept', long_pw)
user = db.get_user_by_email('long@example.com')
print('Stored hash (long):', user['password_hash'][:60] + '...' if user else None)
print('Verify correct long password:', db.verify_password(long_pw, user['password_hash']))
print('Verify wrong password:', db.verify_password('wrong', user['password_hash']))

print('\nCreating user with short password...')
db.create_user('Short User', 'short@example.com', '456', 'Dept', short_pw)
user2 = db.get_user_by_email('short@example.com')
print('Stored hash (short):', user2['password_hash'][:60] + '...' if user2 else None)
print('Verify correct short password:', db.verify_password(short_pw, user2['password_hash']))
print('Verify wrong short password:', db.verify_password('wrong', user2['password_hash']))

print('\nAll tests done.')
