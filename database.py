import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE = "ai_assistant.db"


def get_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def create_tables():
    connection = get_connection()
    cursor = connection.cursor()

    # -----------------------------
    # USERS TABLE
    # -----------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------
    # TASKS TABLE
    # -----------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task TEXT NOT NULL,
            deadline TEXT,
            priority TEXT DEFAULT 'MEDIUM',
            snooze_until TEXT,
            completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # -----------------------------
    # HISTORY TABLE
    # -----------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task TEXT NOT NULL,
            action TEXT NOT NULL,
            deadline TEXT,
            priority TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    connection.commit()
    connection.close()

    print("✅ Database tables created successfully!")


def create_user(name, email, password):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        password_hash = generate_password_hash(password)

        cursor.execute("""
            INSERT INTO users
            (name, email, password_hash)
            VALUES (?, ?, ?)
        """, (name, email, password_hash))

        connection.commit()

        user_id = cursor.lastrowid

        return {
            "success": True,
            "user_id": user_id
        }

    except sqlite3.IntegrityError:
        return {
            "success": False,
            "message": "Email already registered."
        }

    finally:
        connection.close()


def login_user(email, password):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE email = ?
    """, (email,))

    user = cursor.fetchone()

    connection.close()

    if user is None:
        return None

    if check_password_hash(user["password_hash"], password):

        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }

    return None


if __name__ == "__main__":
    create_tables()

    print("🚀 AI Meeting Assistant database is ready!")