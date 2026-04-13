from flask_bcrypt import Bcrypt
import sqlite3

bcrypt = Bcrypt()
conn = sqlite3.connect(r'D:\sqlite\app.db')
c = conn.cursor()

c.execute("SELECT username, password FROM users")
users = c.fetchall()

for username, plain_pw in users:
    if not plain_pw.startswith('$2b$'):  # Já é hash bcrypt?
        hashed = bcrypt.generate_password_hash(plain_pw).decode('utf-8')
        c.execute("UPDATE users SET password = ? WHERE username = ?", (hashed, username))
        print(f"Senha de {username} migrada para hash bcrypt.")

conn.commit()
conn.close()
print("Migração concluída!")