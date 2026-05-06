import bcrypt
import psycopg
from psycopg.rows import dict_row

from .config import get_settings


def verify_password(password, hash_db):
    """Compare a plain password with the stored bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hash_db.encode("utf-8"))


def conect_db():
    """Open a PostgreSQL connection using validated application settings.

    Returns:
        A psycopg connection when the database is reachable, otherwise None.
    """
    settings = get_settings()
    try:
        connection = psycopg.connect(
            host=settings.db_host,
            user=settings.db_user,
            password=settings.db_password,
            dbname=settings.db_name,
            port=settings.db_port,
            row_factory=dict_row,
        )
        return connection
    except psycopg.Error as err:
        print(f"Error connecting to the database: {err}")
        return None


def verify_user(telegram_id):
    """Check whether a Telegram user is linked to an authenticated account."""
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
    """Validate credentials and link the Telegram ID to the database user."""
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
    """Remove the Telegram ID link so the user must log in again later."""
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
    """Return the logged-in username for a Telegram ID, if one exists."""
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