import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, session
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

from google import genai

try:
    from winotify import Notification, audio
    WINOTIFY_AVAILABLE = True
except ImportError:
    WINOTIFY_AVAILABLE = False


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FLASK_SECRET_KEY = os.getenv(
    "FLASK_SECRET_KEY",
    "ai_productivity_agent_secret_2026_deeksha"
)

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "https://ai-productivity-agent-b4hg2895q-deeksha-more.vercel.app"
).strip().rstrip("/")


# =========================================================
# GEMINI AI
# =========================================================

if not GEMINI_API_KEY:

    print("⚠️ GEMINI_API_KEY not found.")

    gemini_client = None

else:

    try:

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("✅ Gemini AI connected!")

    except Exception as error:

        gemini_client = None

        print(
            "❌ Gemini connection failed:",
            error
        )


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = FLASK_SECRET_KEY


# =========================================================
# CORS
# =========================================================

cors_origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    FRONTEND_URL
]

cors_origins = list(
    dict.fromkeys(
        origin.rstrip("/")
        for origin in cors_origins
        if origin
    )
)

CORS(
    app,
    supports_credentials=True,
    origins=cors_origins
)


# =========================================================
# SESSION CONFIGURATION
# =========================================================

# Required because frontend is on Vercel
# and backend is on Render.

app.config["SESSION_COOKIE_NAME"] = "ai_productivity_session"

app.config["SESSION_COOKIE_HTTPONLY"] = True

app.config["SESSION_COOKIE_SECURE"] = True

app.config["SESSION_COOKIE_SAMESITE"] = "None"

app.config["SESSION_COOKIE_PATH"] = "/"

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
    days=7
)


# =========================================================
# DATABASE
# =========================================================

DATABASE = os.getenv(
    "DATABASE_PATH",
    "ai_assistant.db"
)


def get_connection():

    connection = sqlite3.connect(
        DATABASE
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

            FOREIGN KEY (user_id)
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

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    connection.commit()

    connection.close()

    print("✅ Database ready!")


create_tables()


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({

        "system": "AI Productivity Agent",

        "status": "Online",

        "ai": (
            "Gemini Connected"
            if gemini_client
            else
            "Gemini Not Connected"
        )

    })


# =========================================================
# HEALTH
# =========================================================

@app.route("/api/health")
def health():

    return jsonify({

        "system": "AI Productivity Agent",

        "status": "Online",

        "database": "Connected",

        "gemini": (
            "Connected"
            if gemini_client
            else
            "Not Connected"
        )

    })


# =========================================================
# SIGNUP
# =========================================================

@app.route(
    "/signup",
    methods=["POST"]
)
def signup():

    data = request.get_json(
        silent=True
    ) or {}

    name = data.get(
        "name",
        ""
    ).strip()

    email = data.get(
        "email",
        ""
    ).strip().lower()

    password = data.get(
        "password",
        ""
    )


    if not name or not email or not password:

        return jsonify({

            "success": False,

            "message":
            "All fields are required."

        }), 400


    if len(password) < 6:

        return jsonify({

            "success": False,

            "message":
            "Password must contain at least 6 characters."

        }), 400


    connection = get_connection()

    cursor = connection.cursor()


    try:

        password_hash = generate_password_hash(
            password
        )


        cursor.execute("""
            INSERT INTO users
            (name, email, password_hash)
            VALUES (?, ?, ?)
        """, (
            name,
            email,
            password_hash
        ))


        connection.commit()


        user_id = cursor.lastrowid


        session.clear()

        session.permanent = True

        session["user_id"] = user_id

        session["user_name"] = name

        session["user_email"] = email


        return jsonify({

            "success": True,

            "message":
            "Account created successfully!",

            "user": {

                "id": user_id,

                "name": name,

                "email": email

            }

        })


    except sqlite3.IntegrityError:

        return jsonify({

            "success": False,

            "message":
            "Email already registered."

        }), 409


    finally:

        connection.close()


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["POST"]
)
def login():

    data = request.get_json(
        silent=True
    ) or {}


    email = data.get(
        "email",
        ""
    ).strip().lower()

    password = data.get(
        "password",
        ""
    )


    if not email or not password:

        return jsonify({

            "success": False,

            "message":
            "Email and password are required."

        }), 400


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM users
        WHERE email = ?
    """, (
        email,
    ))


    user = cursor.fetchone()


    connection.close()


    if user is None:

        return jsonify({

            "success": False,

            "message":
            "Invalid email or password."

        }), 401


    if not check_password_hash(
        user["password_hash"],
        password
    ):

        return jsonify({

            "success": False,

            "message":
            "Invalid email or password."

        }), 401


    session.clear()

    session.permanent = True

    session["user_id"] = user["id"]

    session["user_name"] = user["name"]

    session["user_email"] = user["email"]


    return jsonify({

        "success": True,

        "message":
        "Login successful!",

        "user": {

            "id": user["id"],

            "name": user["name"],

            "email": user["email"]

        }

    })


# =========================================================
# CURRENT USER
# =========================================================

@app.route("/current-user")
def current_user():

    if "user_id" not in session:

        return jsonify({

            "logged_in": False

        })


    return jsonify({

        "logged_in": True,

        "user": {

            "id":
            session.get("user_id"),

            "name":
            session.get("user_name"),

            "email":
            session.get("user_email")

        }

    })


# =========================================================
# LOGOUT
# =========================================================

@app.route(
    "/logout",
    methods=["POST"]
)
def logout():

    session.clear()

    return jsonify({

        "success": True,

        "message":
        "Logged out successfully."

    })


# =========================================================
# LOGGED-IN USER
# =========================================================

def get_logged_in_user():

    return session.get(
        "user_id"
    )


# =========================================================
# ADD TASK
# =========================================================

@app.route(
    "/add-task",
    methods=["POST"]
)
def add_task():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    data = request.get_json(
        silent=True
    ) or {}


    task = data.get(
        "task",
        ""
    ).strip()

    deadline = data.get(
        "deadline"
    )

    priority = data.get(
        "priority",
        "MEDIUM"
    ).upper()


    if not task:

        return jsonify({

            "success": False,

            "message":
            "Task is required."

        }), 400


    if priority not in [
        "HIGH",
        "MEDIUM",
        "LOW"
    ]:

        priority = "MEDIUM"


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        INSERT INTO tasks
        (user_id, task, deadline, priority)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        task,
        deadline,
        priority
    ))


    task_id = cursor.lastrowid


    cursor.execute("""
        INSERT INTO history
        (user_id, task, action, deadline, priority)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        task,
        "Task Created",
        deadline,
        priority
    ))


    connection.commit()

    connection.close()


    return jsonify({

        "success": True,

        "message":
        "Task added successfully!",

        "task_id":
        task_id

    })


# =========================================================
# GET TASKS
# =========================================================

@app.route("/tasks")
def get_tasks():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE user_id = ?

        ORDER BY
            completed ASC,

            CASE priority
                WHEN 'HIGH' THEN 1
                WHEN 'MEDIUM' THEN 2
                WHEN 'LOW' THEN 3
            END,

            deadline ASC
    """, (
        user_id,
    ))


    tasks = [
        dict(row)
        for row in cursor.fetchall()
    ]


    connection.close()


    return jsonify({

        "success": True,

        "tasks": tasks

    })


# =========================================================
# COMPLETE TASK
# =========================================================

@app.route(
    "/complete-task/<int:task_id>",
    methods=["POST"]
)
def complete_task(task_id):

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

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

            "message":
            "Task not found."

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


    cursor.execute("""
        INSERT INTO history
        (user_id, task, action, deadline, priority)

        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        task["task"],
        "Task Completed",
        task["deadline"],
        task["priority"]
    ))


    connection.commit()

    connection.close()


    return jsonify({

        "success": True,

        "message":
        "Task completed!"

    })


# =========================================================
# DELETE TASK
# =========================================================

@app.route(
    "/delete-task/<int:task_id>",
    methods=["DELETE"]
)
def delete_task(task_id):

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

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

            "message":
            "Task not found."

        }), 404


    cursor.execute("""
        INSERT INTO history
        (user_id, task, action, deadline, priority)

        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        task["task"],
        "Task Deleted",
        task["deadline"],
        task["priority"]
    ))


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


    return jsonify({

        "success": True,

        "message":
        "Task deleted."

    })


# =========================================================
# EDIT TASK
# =========================================================

@app.route(
    "/edit-task/<int:task_id>",
    methods=["PUT"]
)
def edit_task(task_id):

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    data = request.get_json(
        silent=True
    ) or {}


    task_text = data.get(
        "task",
        ""
    ).strip()

    deadline = data.get(
        "deadline"
    )

    priority = data.get(
        "priority",
        "MEDIUM"
    ).upper()


    if not task_text:

        return jsonify({

            "success": False,

            "message":
            "Task is required."

        }), 400


    if priority not in [
        "HIGH",
        "MEDIUM",
        "LOW"
    ]:

        priority = "MEDIUM"


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

            "message":
            "Task not found."

        }), 404


    cursor.execute("""
        UPDATE tasks

        SET task = ?,
            deadline = ?,
            priority = ?

        WHERE id = ?

        AND user_id = ?
    """, (
        task_text,
        deadline,
        priority,
        task_id,
        user_id
    ))


    cursor.execute("""
        INSERT INTO history
        (user_id, task, action, deadline, priority)

        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        task_text,
        "Task Edited",
        deadline,
        priority
    ))


    connection.commit()

    connection.close()


    return jsonify({

        "success": True,

        "message":
        "Task updated successfully!"

    })


# =========================================================
# SNOOZE TASK
# =========================================================

@app.route(
    "/snooze-task/<int:task_id>",
    methods=["POST"]
)
def snooze_task(task_id):

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    data = request.get_json(
        silent=True
    ) or {}


    try:

        minutes = int(
            data.get(
                "minutes",
                10
            )
        )

    except Exception:

        minutes = 10


    if minutes not in [
        10,
        30,
        60
    ]:

        minutes = 10


    snooze_time = (
        datetime.now()
        +
        timedelta(minutes=minutes)
    )


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        UPDATE tasks

        SET snooze_until = ?

        WHERE id = ?

        AND user_id = ?
    """, (
        snooze_time.isoformat(),
        task_id,
        user_id
    ))


    connection.commit()

    connection.close()


    return jsonify({

        "success": True,

        "message":
        f"Task snoozed for {minutes} minutes."

    })


# =========================================================
# HISTORY
# =========================================================

@app.route("/history")
def get_history():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        SELECT *
        FROM history

        WHERE user_id = ?

        ORDER BY timestamp DESC
    """, (
        user_id,
    ))


    history = [
        dict(row)
        for row in cursor.fetchall()
    ]


    connection.close()


    return jsonify({

        "success": True,

        "history": history

    })


# =========================================================
# DELETE HISTORY ITEM
# =========================================================

@app.route(
    "/delete-history/<int:history_id>",
    methods=["DELETE"]
)
def delete_history(history_id):

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

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

    connection.close()


    return jsonify({

        "success": True,

        "message":
        "History item deleted."

    })


# =========================================================
# CLEAR ALL TASKS
# =========================================================

@app.route(
    "/clear-tasks",
    methods=["DELETE"]
)
def clear_tasks():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        DELETE FROM tasks

        WHERE user_id = ?
    """, (
        user_id,
    ))


    connection.commit()

    connection.close()


    return jsonify({

        "success": True,

        "message":
        "All tasks cleared."

    })


# =========================================================
# PRODUCTIVITY INSIGHTS
# =========================================================

@app.route(
    "/productivity-insights"
)
def productivity_insights():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        SELECT COUNT(*) AS count

        FROM tasks

        WHERE user_id = ?
    """, (
        user_id,
    ))


    total = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count

        FROM tasks

        WHERE user_id = ?

        AND completed = 1
    """, (
        user_id,
    ))


    completed = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count

        FROM tasks

        WHERE user_id = ?

        AND completed = 0
    """, (
        user_id,
    ))


    pending = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count

        FROM tasks

        WHERE user_id = ?

        AND completed = 0

        AND priority = 'HIGH'
    """, (
        user_id,
    ))


    high = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count

        FROM tasks

        WHERE user_id = ?

        AND completed = 0

        AND priority = 'MEDIUM'
    """, (
        user_id,
    ))


    medium = cursor.fetchone()["count"]


    cursor.execute("""
        SELECT COUNT(*) AS count

        FROM tasks

        WHERE user_id = ?

        AND completed = 0

        AND priority = 'LOW'
    """, (
        user_id,
    ))


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

        "total": total,

        "completed": completed,

        "pending": pending,

        "high": high,

        "medium": medium,

        "low": low,

        "completion_rate":
        completion_rate

    })


# =========================================================
# AI TASK ANALYZER
# =========================================================

@app.route(
    "/ai-analyze",
    methods=["POST"]
)
def ai_analyze():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    if not gemini_client:

        return jsonify({

            "success": False,

            "message":
            "Gemini AI is not connected."

        }), 500


    data = request.get_json(
        silent=True
    ) or {}


    task_text = data.get(
        "task",
        ""
    ).strip()


    if not task_text:

        return jsonify({

            "success": False,

            "message":
            "Please enter a task."

        }), 400


    prompt = f"""
You are an AI productivity assistant.

Analyze this user's task:

"{task_text}"

Return a concise productivity analysis.

Use exactly these sections:

TASK:
PRIORITY:
REASON:
SUGGESTED_DEADLINE:
ACTION:

Priority must be one of:

HIGH
MEDIUM
LOW

Keep the response practical and easy to understand.

Do not invent personal information.
"""


    try:

        response = gemini_client.models.generate_content(

            model="gemini-3.5-flash",

            contents=prompt

        )


        return jsonify({

            "success": True,

            "ai_response":
            response.text

        })


    except Exception as error:

        print(
            "Gemini error:",
            error
        )


        return jsonify({

            "success": False,

            "message":
            "Gemini AI could not process the task.",

            "error":
            str(error)

        }), 500


# =========================================================
# AI DAILY PLANNER
# =========================================================

@app.route(
    "/ai-daily-plan",
    methods=["GET"]
)
def ai_daily_plan():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    if not gemini_client:

        return jsonify({

            "success": False,

            "message":
            "Gemini AI is not connected."

        }), 500


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        SELECT id, task, deadline, priority

        FROM tasks

        WHERE user_id = ?

        AND completed = 0

        ORDER BY deadline ASC
    """, (
        user_id,
    ))


    tasks = [
        dict(row)
        for row in cursor.fetchall()
    ]


    connection.close()


    if not tasks:

        return jsonify({

            "success": True,

            "plan":
            "You currently have no pending tasks."

        })


    task_text = ""


    for index, task in enumerate(
        tasks,
        start=1
    ):

        task_text += (

            f"{index}. "

            f"Task: {task['task']} | "

            f"Deadline: {task['deadline']} | "

            f"Priority: {task['priority']}\n"

        )


    prompt = f"""
You are an intelligent personal productivity agent.

Create a realistic daily plan for the user.

Pending tasks:

{task_text}

Instructions:

1. Prioritize urgent and HIGH priority tasks.
2. Consider deadlines.
3. Create a simple order for completing the tasks.
4. Explain briefly why the order makes sense.
5. Include short breaks where appropriate.
6. Do not invent tasks.
7. Keep the response concise.

Use this format:

TODAY'S PLAN

1. Task
   Why:

2. Task
   Why:

BREAKS

FINAL TIP
"""


    try:

        response = gemini_client.models.generate_content(

            model="gemini-3.5-flash",

            contents=prompt

        )


        return jsonify({

            "success": True,

            "plan":
            response.text

        })


    except Exception as error:

        print(
            "Gemini planner error:",
            error
        )


        return jsonify({

            "success": False,

            "message":
            "Gemini could not create the daily plan.",

            "error":
            str(error)

        }), 500


# =========================================================
# AI PRODUCTIVITY COACH
# =========================================================

@app.route(
    "/ai-coach",
    methods=["POST"]
)
def ai_coach():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    if not gemini_client:

        return jsonify({

            "success": False,

            "message":
            "Gemini AI is not connected."

        }), 500


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        SELECT task, deadline, priority, completed

        FROM tasks

        WHERE user_id = ?
    """, (
        user_id,
    ))


    tasks = [
        dict(row)
        for row in cursor.fetchall()
    ]


    connection.close()


    prompt = f"""
You are a friendly AI productivity coach.

Here is the user's current task data:

{tasks}

Give the user:

1. A short productivity observation.
2. One thing they should focus on.
3. One practical suggestion.
4. One motivating sentence.

Keep it concise.

Do not make assumptions about the user's personal life.
"""


    try:

        response = gemini_client.models.generate_content(

            model="gemini-3.5-flash",

            contents=prompt

        )


        return jsonify({

            "success": True,

            "coach":
            response.text

        })


    except Exception as error:

        print(
            "Gemini coach error:",
            error
        )


        return jsonify({

            "success": False,

            "message":
            "AI coach could not respond.",

            "error":
            str(error)

        }), 500


# =========================================================
# OLD DAILY PLAN ROUTE
# =========================================================

@app.route("/daily-plan")
def daily_plan():

    user_id = get_logged_in_user()


    if not user_id:

        return jsonify({

            "success": False,

            "message":
            "Please login first."

        }), 401


    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        SELECT id, task, deadline, priority

        FROM tasks

        WHERE user_id = ?

        AND completed = 0

        ORDER BY

            CASE priority

                WHEN 'HIGH' THEN 1

                WHEN 'MEDIUM' THEN 2

                WHEN 'LOW' THEN 3

            END,

            deadline ASC
    """, (
        user_id,
    ))


    tasks = [
        dict(row)
        for row in cursor.fetchall()
    ]


    connection.close()


    return jsonify({

        "success": True,

        "plan": tasks

    })


# =========================================================
# REMINDER SYSTEM
# =========================================================

reminded_tasks = set()


def reminder_worker():

    print(
        "⏰ Reminder system started."
    )


    while True:

        try:

            connection = get_connection()

            cursor = connection.cursor()


            cursor.execute("""
                SELECT *

                FROM tasks

                WHERE completed = 0

                AND deadline IS NOT NULL

                AND snooze_until IS NULL
            """)


            tasks = cursor.fetchall()


            connection.close()


            now = datetime.now()


            for task in tasks:

                try:

                    deadline = datetime.fromisoformat(
                        task["deadline"]
                    )

                except Exception:

                    continue


                reminder_time = (
                    deadline
                    -
                    timedelta(minutes=5)
                )


                key = (
                    f"{task['user_id']}_{task['id']}"
                )


                if (
                    now >= reminder_time
                    and
                    now <= deadline
                ):

                    if key not in reminded_tasks:

                        print(
                            f"🔔 Reminder: {task['task']}"
                        )


                        if WINOTIFY_AVAILABLE:

                            try:

                                toast = Notification(

                                    app_id=
                                    "AI Productivity Agent",

                                    title=
                                    "Task Reminder",

                                    msg=(
                                        f"{task['task']} "
                                        f"is due soon."
                                    )

                                )


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


                        reminded_tasks.add(
                            key
                        )


        except Exception as error:

            print(
                "Reminder worker error:",
                error
            )


        time.sleep(30)


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    enable_desktop_reminders = (

        os.getenv(
            "ENABLE_DESKTOP_REMINDERS",
            "true"
        ).lower() == "true"

        and

        WINOTIFY_AVAILABLE

    )


    if enable_desktop_reminders:

        reminder_thread = threading.Thread(

            target=reminder_worker,

            daemon=True

        )

        reminder_thread.start()

    else:

        print(
            "⏰ Desktop reminders disabled "
            "(hosted/non-Windows mode)."
        )


    print("")

    print(
        "========================================"
    )

    print(
        "🚀 AI PRODUCTIVITY AGENT"
    )

    print(
        "========================================"
    )

    print(
        "🌐 Backend running"
    )

    if gemini_client:

        print(
            "🤖 Gemini AI: Connected"
        )

    else:

        print(
            "🤖 Gemini AI: Not Connected"
        )


    print(
        "⏰ Reminder System: Running"
    )

    print(
        "========================================"
    )

    print("")


    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )


    app.run(

        host="0.0.0.0",

        port=port,

        debug=False,

        use_reloader=False

    )