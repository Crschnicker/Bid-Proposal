from werkzeug.security import generate_password_hash

passwords = {
    'superadmin': 'Sound#Power23!',
    'tom': 'Bass@24',
    'mosies': 'Care!4%',
    'cammie': 'Scully$6',
    'staff': 'Tower99!'
}

for username, password in passwords.items():
    hash = generate_password_hash(password)
    print(f"UPDATE \"user\" SET password_hash = '{hash}' WHERE username = '{username}';")