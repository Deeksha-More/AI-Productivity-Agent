import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, session
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from winotify import Notification, audio
except ImportError:
    Notification = None
    audio = None


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing from the .env file."
    )


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)
app.secret_key = SECRET_KEY

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

CORS(
    app,
    supports_credentials=True
)


# ============================================================
# DATABASE
# ============================================================

DATABASE = "ai_assistant.db"


def get_connection():
    connection = sqlite3.connect(
        DATABASE,
        timeout=10
    )

    connection.row_factory = sqlite3.Row

    return connection


def create_tables():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

            FOREIGN KEY(user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task TEXT NOT NULL,
            action TEXT NOT NULL,
            deadline TEXT,
            priority TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    connection.commit()
    connection.close()


create_tables()


# ============================================================
# AUTHENTICATION
# ============================================================

def get_current_user_id():
    return session.get("user_id")


def login_required():
    user_id = get_current_user_id()

    if not user_id:
        return None

    return user_id


# ============================================================
# HISTORY HELPER
# ============================================================

def add_history(
    user_id,
    task,
    action,
    deadline=None,
    priority="MEDIUM"
):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO history (
            user_id,
            task,
            action,
            deadline,
            priority
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        task,
        action,
        deadline,
        priority
    ))

    connection.commit()
    connection.close()


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return jsonify({
        "message": "AI Productivity Agent Backend is running!",
        "status": "success"
    })


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health")
def health():

    return jsonify({
        "system": "AI Productivity Agent",
        "status": "Online",
        "database": "Connected"
    })


# ============================================================
# SIGNUP
# ============================================================

@app.route("/signup", methods=["POST"])
def signup():

    data = request.get_json() or {}

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))


    if not name:

        return jsonify({
            "success": False,
            "message": "Name is required."
        }), 400


    if not email:

        return jsonify({
            "success": False,
            "message": "Email is required."
        }), 400


    if not password:

        return jsonify({
            "success": False,
            "message": "Password is required."
        }), 400


    if len(password) < 6:

        return jsonify({
            "success": False,
            "message": "Password must contain at least 6 characters."
        }), 400


    password_hash = generate_password_hash(password)


    connection = get_connection()
    cursor = connection.cursor()


    try:

        cursor.execute("""
            INSERT INTO users (
                name,
                email,
                password_hash
            )
            VALUES (?, ?, ?)
        """, (
            name,
            email,
            password_hash
        ))

        connection.commit()

        user_id = cursor.lastrowid

        session["user_id"] = user_id
        session["user_name"] = name
        session["user_email"] = email


        return jsonify({
            "success": True,
            "message": "Account created successfully!",
            "user": {
                "id": user_id,
                "name": name,
                "email": email
            }
        })


    except sqlite3.IntegrityError:

        return jsonify({
            "success": False,
            "message": "Email already registered."
        }), 409


    finally:

        connection.close()


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json() or {}

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))


    if not email or not password:

        return jsonify({
            "success": False,
            "message": "Email and password are required."
        }), 400


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM users
        WHERE email = ?
    """, (email,))


    user = cursor.fetchone()

    connection.close()


    if not user:

        return jsonify({
            "success": False,
            "message": "Invalid email or password."
        }), 401


    if not check_password_hash(
        user["password_hash"],
        password
    ):

        return jsonify({
            "success": False,
            "message": "Invalid email or password."
        }), 401


    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]


    return jsonify({
        "success": True,
        "message": "Login successful!",
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    })


# ============================================================
# CURRENT USER
# ============================================================

@app.route("/current-user")
def current_user():

    user_id = get_current_user_id()


    if not user_id:

        return jsonify({
            "logged_in": False
        })


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT
            id,
            name,
            email
        FROM users
        WHERE id = ?
    """, (user_id,))


    user = cursor.fetchone()

    connection.close()


    if not user:

        session.clear()

        return jsonify({
            "logged_in": False
        })


    return jsonify({
        "logged_in": True,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    })


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout", methods=["POST"])
def logout():

    session.clear()

    return jsonify({
        "success": True,
        "message": "Logged out successfully."
    })


# ============================================================
# ADD TASK
# ============================================================

@app.route("/add-task", methods=["POST"])
def add_task():

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    data = request.get_json() or {}

    task = str(data.get("task", "")).strip()
    deadline = data.get("deadline")

    priority = str(
        data.get("priority", "MEDIUM")
    ).upper()


    if not task:

        return jsonify({
            "success": False,
            "message": "Task cannot be empty."
        }), 400


    if priority not in ["HIGH", "MEDIUM", "LOW"]:
        priority = "MEDIUM"


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        INSERT INTO tasks (
            user_id,
            task,
            deadline,
            priority
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        task,
        deadline,
        priority
    ))


    connection.commit()

    task_id = cursor.lastrowid

    connection.close()


    add_history(
        user_id,
        task,
        "Task Added",
        deadline,
        priority
    )


    return jsonify({
        "success": True,
        "message": "Task added successfully.",
        "task_id": task_id
    })


# ============================================================
# GET TASKS
# ============================================================

@app.route("/tasks")
def get_tasks():

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT
            id,
            task,
            deadline,
            priority,
            snooze_until,
            completed,
            created_at
        FROM tasks
        WHERE user_id = ?
        ORDER BY
            completed ASC,
            CASE
                WHEN deadline IS NULL THEN 1
                ELSE 0
            END,
            deadline ASC
    """, (user_id,))


    rows = cursor.fetchall()

    connection.close()


    tasks = [
        dict(row)
        for row in rows
    ]


    return jsonify({
        "success": True,
        "tasks": tasks
    })


# ============================================================
# COMPLETE TASK
# ============================================================

@app.route(
    "/complete-task/<int:task_id>",
    methods=["POST"]
)
def complete_task(task_id):

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE id = ?
        AND user_id = ?
    """, (
        task_id,
        user_id
    ))


    task = cursor.fetchone()


    if not task:

        connection.close()

        return jsonify({
            "success": False,
            "message": "Task not found."
        }), 404


    cursor.execute("""
        UPDATE tasks
        SET completed = 1
        WHERE id = ?
        AND user_id = ?
    """, (
        task_id,
        user_id
    ))


    connection.commit()
    connection.close()


    add_history(
        user_id,
        task["task"],
        "Task Completed",
        task["deadline"],
        task["priority"]
    )


    return jsonify({
        "success": True,
        "message": "Task completed."
    })


# ============================================================
# DELETE TASK
# ============================================================

@app.route(
    "/delete-task/<int:task_id>",
    methods=["DELETE"]
)
def delete_task(task_id):

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE id = ?
        AND user_id = ?
    """, (
        task_id,
        user_id
    ))


    task = cursor.fetchone()


    if not task:

        connection.close()

        return jsonify({
            "success": False,
            "message": "Task not found."
        }), 404


    cursor.execute("""
        DELETE FROM tasks
        WHERE id = ?
        AND user_id = ?
    """, (
        task_id,
        user_id
    ))


    connection.commit()
    connection.close()


    add_history(
        user_id,
        task["task"],
        "Task Deleted",
        task["deadline"],
        task["priority"]
    )


    return jsonify({
        "success": True,
        "message": "Task deleted."
    })


# ============================================================
# EDIT TASK
# ============================================================

@app.route(
    "/edit-task/<int:task_id>",
    methods=["PUT"]
)
def edit_task(task_id):

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    data = request.get_json() or {}


    new_task = str(
        data.get("task", "")
    ).strip()


    new_deadline = data.get("deadline")


    new_priority = str(
        data.get("priority", "MEDIUM")
    ).upper()


    if not new_task:

        return jsonify({
            "success": False,
            "message": "Task cannot be empty."
        }), 400


    if new_priority not in ["HIGH", "MEDIUM", "LOW"]:
        new_priority = "MEDIUM"


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE id = ?
        AND user_id = ?
    """, (
        task_id,
        user_id
    ))


    old_task = cursor.fetchone()


    if not old_task:

        connection.close()

        return jsonify({
            "success": False,
            "message": "Task not found."
        }), 404


    cursor.execute("""
        UPDATE tasks
        SET
            task = ?,
            deadline = ?,
            priority = ?
        WHERE id = ?
        AND user_id = ?
    """, (
        new_task,
        new_deadline,
        new_priority,
        task_id,
        user_id
    ))


    connection.commit()
    connection.close()


    add_history(
        user_id,
        new_task,
        "Task Edited",
        new_deadline,
        new_priority
    )


    return jsonify({
        "success": True,
        "message": "Task updated successfully."
    })


# ============================================================
# SNOOZE TASK
# ============================================================

@app.route(
    "/snooze-task/<int:task_id>",
    methods=["POST"]
)
def snooze_task(task_id):

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    data = request.get_json() or {}

    try:
        minutes = int(
            data.get("minutes", 10)
        )
    except (ValueError, TypeError):
        minutes = 10


    if minutes not in [10, 30, 60]:
        minutes = 10


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE id = ?
        AND user_id = ?
    """, (
        task_id,
        user_id
    ))


    task = cursor.fetchone()


    if not task:

        connection.close()

        return jsonify({
            "success": False,
            "message": "Task not found."
        }), 404


    snooze_until = (
        datetime.now() +
        timedelta(minutes=minutes)
    ).isoformat()


    cursor.execute("""
        UPDATE tasks
        SET snooze_until = ?
        WHERE id = ?
        AND user_id = ?
    """, (
        snooze_until,
        task_id,
        user_id
    ))


    connection.commit()
    connection.close()


    add_history(
        user_id,
        task["task"],
        f"Task Snoozed for {minutes} minutes",
        task["deadline"],
        task["priority"]
    )


    return jsonify({
        "success": True,
        "message": f"Task snoozed for {minutes} minutes."
    })


# ============================================================
# HISTORY
# ============================================================

@app.route("/history")
def get_history():

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT
            id,
            task,
            action,
            deadline,
            priority,
            timestamp
        FROM history
        WHERE user_id = ?
        ORDER BY timestamp DESC
    """, (user_id,))


    rows = cursor.fetchall()

    connection.close()


    history = [
        dict(row)
        for row in rows
    ]


    return jsonify({
        "success": True,
        "history": history
    })


# ============================================================
# DELETE HISTORY
# ============================================================

@app.route(
    "/delete-history/<int:history_id>",
    methods=["DELETE"]
)
def delete_history(history_id):

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        DELETE FROM history
        WHERE id = ?
        AND user_id = ?
    """, (
        history_id,
        user_id
    ))


    connection.commit()

    deleted = cursor.rowcount

    connection.close()


    if deleted == 0:

        return jsonify({
            "success": False,
            "message": "History item not found."
        }), 404


    return jsonify({
        "success": True,
        "message": "History deleted."
    })


# ============================================================
# CLEAR ALL TASKS
# ============================================================

@app.route(
    "/clear-tasks",
    methods=["DELETE"]
)
def clear_tasks():

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE user_id = ?
    """, (user_id,))


    tasks = cursor.fetchall()


    for task in tasks:

        add_history(
            user_id,
            task["task"],
            "Task Cleared",
            task["deadline"],
            task["priority"]
        )


    cursor.execute("""
        DELETE FROM tasks
        WHERE user_id = ?
    """, (user_id,))


    connection.commit()
    connection.close()


    return jsonify({
        "success": True,
        "message": "All tasks cleared."
    })


# ============================================================
# PRODUCTIVITY INSIGHTS
# ============================================================

@app.route("/productivity-insights")
def productivity_insights():

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
    """, (user_id,))

    total = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
        AND completed = 1
    """, (user_id,))

    completed = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
        AND completed = 0
    """, (user_id,))

    pending = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
        AND priority = 'HIGH'
    """, (user_id,))

    high = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
        AND priority = 'MEDIUM'
    """, (user_id,))

    medium = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
        AND priority = 'LOW'
    """, (user_id,))

    low = cursor.fetchone()["count"]


    connection.close()


    completion_rate = 0

    if total > 0:

        completion_rate = round(
            (completed / total) * 100,
            1
        )


    return jsonify({

        "success": True,

        "insights": {

            "total_tasks": total,

            "completed_tasks": completed,

            "pending_tasks": pending,

            "completion_rate": completion_rate,

            "high_priority": high,

            "medium_priority": medium,

            "low_priority": low

        }

    })


# ============================================================
# DAILY PLAN
# ============================================================

@app.route("/daily-plan")
def daily_plan():

    user_id = login_required()


    if not user_id:

        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute("""
        SELECT
            task,
            deadline,
            priority
        FROM tasks
        WHERE user_id = ?
        AND completed = 0
        ORDER BY
            CASE priority
                WHEN 'HIGH' THEN 1
                WHEN 'MEDIUM' THEN 2
                WHEN 'LOW' THEN 3
            END,
            CASE
                WHEN deadline IS NULL THEN 1
                ELSE 0
            END,
            deadline ASC
    """, (user_id,))


    tasks = cursor.fetchall()

    connection.close()


    if not tasks:

        plan = """
🎉 You have no pending tasks.

Enjoy your free time or add a new task!
"""

        return jsonify({
            "success": True,
            "plan": plan
        })


    lines = []

    lines.append("🤖 YOUR SMART DAILY PLAN")
    lines.append("")
    lines.append(
        "Start with your highest-priority tasks:"
    )
    lines.append("")


    for index, task in enumerate(
        tasks,
        start=1
    ):

        deadline = (
            task["deadline"]
            if task["deadline"]
            else "No deadline"
        )


        lines.append(
            f"{index}. "
            f"[{task['priority']}] "
            f"{task['task']} "
            f"— {deadline}"
        )


    lines.append("")

    lines.append(
        "💡 Focus on one task at a time "
        "and complete high-priority work first."
    )


    return jsonify({
        "success": True,
        "plan": "\n".join(lines)
    })


# ============================================================
# WINDOWS NOTIFICATION
# ============================================================

reminded_tasks = set()


def send_notification(task):

    if Notification is None:
        return


    try:

        toast = Notification(
            app_id="AI Productivity Agent",
            title="⏰ Task Reminder",
            msg=task
        )


        if audio is not None:

            toast.set_audio(
                audio.Default,
                loop=False
            )


        toast.show()


    except Exception as error:

        print(
            "Notification error:",
            error
        )


# ============================================================
# REMINDER WORKER
# ============================================================

def reminder_worker():

    print("🔔 Reminder system started.")


    while True:

        try:

            connection = get_connection()
            cursor = connection.cursor()


            cursor.execute("""
                SELECT
                    id,
                    user_id,
                    task,
                    deadline,
                    snooze_until,
                    completed
                FROM tasks
                WHERE completed = 0
                AND deadline IS NOT NULL
            """)


            tasks = cursor.fetchall()

            connection.close()


            now = datetime.now()


            for task in tasks:

                try:

                    deadline = datetime.fromisoformat(
                        task["deadline"]
                    )

                except (ValueError, TypeError):

                    continue


                reminder_time = (
                    deadline -
                    timedelta(minutes=5)
                )


                key = (
                    f"{task['user_id']}_{task['id']}"
                )


                if (
                    now >= reminder_time
                    and
                    now <= deadline
                    and
                    key not in reminded_tasks
                ):

                    send_notification(
                        task["task"]
                    )

                    reminded_tasks.add(key)


                if now > deadline:

                    reminded_tasks.add(key)


        except Exception as error:

            print(
                "Reminder worker error:",
                error
            )


        time.sleep(30)


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "🚀 AI Productivity Agent Backend Starting..."
    )

    print(
        "🔐 Secure session key loaded from .env"
    )

    print(
        "🗄️ SQLite database connected"
    )

    print(
        "👥 Multi-user authentication enabled"
    )

    print(
        "🔔 Reminder system enabled"
    )

    print(
        "🌐 Backend: http://127.0.0.1:5000"
    )

    print("")


    reminder_thread = threading.Thread(
        target=reminder_worker,
        daemon=True
    )

    reminder_thread.start()


    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )