import os

import bcrypt
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()


# Function to hash a password using bcrypt
def verify_password(password, hash_db):
    return bcrypt.checkpw(password.encode("utf-8"), hash_db.encode("utf-8"))


def conect_db():
    try:
        connection = psycopg.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            dbname=os.getenv("DB_NAME"),
            port=os.getenv("DB_PORT"),
            row_factory=dict_row,
        )
        return connection
    except psycopg.Error as err:
        print(f"Error connecting to the database: {err}")
        return None


def verify_user(telegram_id):
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def login_user(username, password, telegram_id):
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, password FROM users WHERE username = %s",
                (username,),
            )
            user = cursor.fetchone()

            if not user or not verify_password(password, user["password"]):
                return False

            cursor.execute(
                "UPDATE users SET telegram_id = %s WHERE id = %s",
                (telegram_id, user["id"]),
            )
            conn.commit()
            return True
    finally:
        conn.close()


def logout_user(telegram_id):
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET telegram_id = NULL WHERE telegram_id = %s",
                (telegram_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
    finally:
        conn.close()


def status_user(telegram_id):
    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT username FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()
