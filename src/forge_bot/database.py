import mysql.connector
import os
from dotenv import load_dotenv
import bcrypt

load_dotenv()

# Function to hash a password using bcrypt
def verify_password(password, hash_db):
    return bcrypt.checkpw(password.encode('utf-8'), hash_db.encode('utf-8'))

def conect_db():
    try:
        conexion = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            port=os.getenv("DB_PORT")
        )
        return conexion
    except mysql.connector.Error as err:
        print(f"Error connecting to the database: {err}")
        return None
    

def verify_user(telegram_id):
    conn = conect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

def login_user(username, password, telegram_id):
    conn = conect_db()
    if not conn: return False
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, password FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if user and verify_password(password, user['password']):
            cursor.execute("UPDATE users SET telegram_id = %s WHERE id = %s", (telegram_id, user['id']))
            conn.commit()
            return True
        return False
    finally:
        conn.close()

def logout_user(telegram_id):
    conn = conect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET telegram_id = NULL WHERE telegram_id = %s", (telegram_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def status_user(telegram_id):
    conn = conect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT username FROM users WHERE telegram_id = %s", (telegram_id,))
    return cursor.fetchone()