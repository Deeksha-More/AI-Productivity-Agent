import os
import sqlite3
import threading
import secrets
import hashlib
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, session
from werkzeug.utils import secure_filename
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

from google import genai

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

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
    "ai_productivity_agent_secret_2026"
)

if not GEMINI_API_KEY:
    print("⚠️ GEMINI_API_KEY not found in .env")
    gemini_client = None
else:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Gemini AI connected!")
    except Exception as error:
        gemini_client = None
        print("❌ Gemini connection failed:", error)


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = FLASK_SECRET_KEY

# Maximum document upload size: 8 MB
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

CORS(
    app,
    supports_credentials=True,
    origins=[
        r"https://.*\.vercel\.app",
        "http://127.0.0.1:5500",
        "http://localhost:5500"
    ]
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True

# Render + Vercel are cross-site in production, so session cookies must
# be Secure and SameSite=None. Keep local HTTP development working too.
IS_PRODUCTION = bool(os.getenv("RENDER")) or os.getenv(
    "RENDER_EXTERNAL_URL", ""
).startswith("https://")

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None" if IS_PRODUCTION else "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION


# =========================================================
# DOCUMENT ANALYZER
# =========================================================

ALLOWED_DOCUMENT_EXTENSIONS = {".txt", ".pdf", ".docx"}
MAX_DOCUMENT_SIZE = 8 * 1024 * 1024

def _extract_document_text(file_storage):
    filename = secure_filename(file_storage.filename or "")
    extension = os.path.splitext(filename)[1].lower()

    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError("Supported files are TXT, PDF and DOCX.")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_DOCUMENT_SIZE:
        raise ValueError("Document is too large. Maximum size is 8 MB.")

    if extension == ".txt":
        text = file_storage.stream.read().decode("utf-8", errors="replace")

    elif extension == ".pdf":
        if PdfReader is None:
            raise RuntimeError("PDF support is not installed. Add pypdf to requirements.txt and redeploy.")
        reader = PdfReader(file_storage.stream)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)

    else:
        if Document is None:
            raise RuntimeError("DOCX support is not installed. Add python-docx to requirements.txt and redeploy.")
        document = Document(file_storage.stream)
        text = "\n".join(p.text for p in document.paragraphs)

    text = text.strip()
    if not text:
        raise ValueError("No readable text was found in the document.")

    # Keep the prompt bounded while preserving the beginning of the document.
    return filename, text[:50000]


# =========================================================
# DATABASE
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "ai_assistant.db")


def get_connection():
    connection = sqlite3.connect(DATABASE)
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            content TEXT NOT NULL,
            analysis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    connection.commit()
    connection.close()

    print("✅ Database ready!")


# IMPORTANT: Gunicorn/Render imports this module instead of running
# `python backend.py`, so the database must be initialized at import time.
try:
    create_tables()
except Exception as error:
    print("❌ Database initialization failed:", error)
    raise


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "system": "AI Productivity Agent",
        "status": "Online",
        "ai": "Gemini Connected" if gemini_client else "Gemini Not Connected"
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
        "gemini": "Connected" if gemini_client else "Not Connected"
    })


# =========================================================
# TOKEN AUTHENTICATION
# =========================================================

def _hash_auth_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_auth_token(user_id):
    token = secrets.token_urlsafe(48)
    token_hash = _hash_auth_token(token)
    expires_at = datetime.utcnow() + timedelta(days=30)

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "DELETE FROM auth_tokens WHERE expires_at < ?",
        (datetime.utcnow().isoformat(),)
    )
    cursor.execute("""
        INSERT INTO auth_tokens (user_id, token_hash, expires_at)
        VALUES (?, ?, ?)
    """, (user_id, token_hash, expires_at.isoformat()))
    connection.commit()
    connection.close()
    return token


def _get_token_user_id():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:].strip()
    if not token:
        return None

    token_hash = _hash_auth_token(token)
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
        SELECT user_id
        FROM auth_tokens
        WHERE token_hash = ?
        AND expires_at > ?
    """, (token_hash, datetime.utcnow().isoformat()))
    row = cursor.fetchone()
    connection.close()
    return row["user_id"] if row else None


def _revoke_auth_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return
    token = auth_header[7:].strip()
    if not token:
        return
    connection = get_connection()
    connection.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (_hash_auth_token(token),))
    connection.commit()
    connection.close()


# =========================================================
# SIGNUP
# =========================================================

@app.route("/signup", methods=["POST"])
def signup():

    data = request.get_json()

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:

        return jsonify({
            "success": False,
            "message": "All fields are required."
        }), 400

    if len(password) < 6:

        return jsonify({
            "success": False,
            "message": "Password must contain at least 6 characters."
        }), 400

    connection = get_connection()
    cursor = connection.cursor()

    try:

        password_hash = generate_password_hash(password)

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

        session["user_id"] = user_id
        session["user_name"] = name
        session["user_email"] = email

        auth_token = _create_auth_token(user_id)

        return jsonify({
            "success": True,
            "message": "Account created successfully!",
            "token": auth_token,
            "expires_in_days": 30,
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


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json()

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

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

    auth_token = _create_auth_token(user["id"])

    return jsonify({
        "success": True,
        "message": "Login successful!",
        "token": auth_token,
        "expires_in_days": 30,
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

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({"logged_in": False})

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    connection.close()

    if user is None:
        return jsonify({"logged_in": False})

    return jsonify({
        "logged_in": True,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    })


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout", methods=["POST"])
def logout():

    _revoke_auth_token()
    session.clear()

    return jsonify({
        "success": True,
        "message": "Logged out successfully."
    })


# =========================================================
# LOGIN CHECK
# =========================================================

def get_logged_in_user():

    token_user_id = _get_token_user_id()
    if token_user_id:
        return token_user_id

    return session.get("user_id")


# =========================================================
# ADD TASK
# =========================================================

@app.route("/add-task", methods=["POST"])
def add_task():

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    data = request.get_json()

    task = data.get("task", "").strip()
    deadline = data.get("deadline")
    priority = data.get("priority", "MEDIUM").upper()

    if not task:

        return jsonify({
            "success": False,
            "message": "Task is required."
        }), 400

    if priority not in ["HIGH", "MEDIUM", "LOW"]:
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
        "message": "Task added successfully!",
        "task_id": task_id
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
            "message": "Please login first."
        }), 401

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE user_id = ?
        ORDER BY completed ASC,
                 CASE priority
                     WHEN 'HIGH' THEN 1
                     WHEN 'MEDIUM' THEN 2
                     WHEN 'LOW' THEN 3
                 END,
                 deadline ASC
    """, (user_id,))

    tasks = [dict(row) for row in cursor.fetchall()]

    connection.close()

    return jsonify({
        "success": True,
        "tasks": tasks
    })


# =========================================================
# COMPLETE TASK
# =========================================================

@app.route("/complete-task/<int:task_id>", methods=["POST"])
def complete_task(task_id):

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
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
        "message": "Task completed!"
    })


# =========================================================
# DELETE TASK
# =========================================================

@app.route("/delete-task/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
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
        "message": "Task deleted."
    })


# =========================================================
# EDIT TASK
# =========================================================

@app.route("/edit-task/<int:task_id>", methods=["PUT"])
def edit_task(task_id):

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    data = request.get_json()

    task_text = data.get("task", "").strip()
    deadline = data.get("deadline")
    priority = data.get("priority", "MEDIUM").upper()

    if priority not in ["HIGH", "MEDIUM", "LOW"]:
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
            "message": "Task not found."
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
        "message": "Task updated successfully!"
    })


# =========================================================
# SNOOZE TASK
# =========================================================

@app.route("/snooze-task/<int:task_id>", methods=["POST"])
def snooze_task(task_id):

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    data = request.get_json()

    minutes = int(data.get("minutes", 10))

    snooze_time = datetime.now() + timedelta(minutes=minutes)

    snooze_string = snooze_time.isoformat()

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE tasks
        SET snooze_until = ?
        WHERE id = ?
        AND user_id = ?
    """, (
        snooze_string,
        task_id,
        user_id
    ))

    connection.commit()
    connection.close()

    return jsonify({
        "success": True,
        "message": f"Task snoozed for {minutes} minutes."
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
            "message": "Please login first."
        }), 401

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM history
        WHERE user_id = ?
        ORDER BY timestamp DESC
    """, (user_id,))

    history = [dict(row) for row in cursor.fetchall()]

    connection.close()

    return jsonify({
        "success": True,
        "history": history
    })


# =========================================================
# DELETE HISTORY ITEM
# =========================================================

@app.route("/delete-history/<int:history_id>", methods=["DELETE"])
def delete_history(history_id):

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
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
        "message": "History item deleted."
    })


# =========================================================
# CLEAR ALL TASKS
# =========================================================

@app.route("/clear-tasks", methods=["DELETE"])
def clear_tasks():

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    connection = get_connection()
    cursor = connection.cursor()

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


# =========================================================
# CLEAR ALL HISTORY (CURRENT USER ONLY)
# =========================================================

@app.route("/clear-history", methods=["DELETE"])
def clear_history():

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM history
        WHERE user_id = ?
    """, (user_id,))

    deleted_count = cursor.rowcount

    connection.commit()
    connection.close()

    return jsonify({
        "success": True,
        "message": "All history records cleared.",
        "deleted_count": deleted_count
    })


# =========================================================
# PRODUCTIVITY INSIGHTS
# =========================================================

@app.route("/productivity-insights")
def productivity_insights():

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
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
        AND completed = 0
        AND priority = 'HIGH'
    """, (user_id,))

    high = cursor.fetchone()["count"]

    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
        AND completed = 0
        AND priority = 'MEDIUM'
    """, (user_id,))

    medium = cursor.fetchone()["count"]

    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE user_id = ?
        AND completed = 0
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
        "total": total,
        "completed": completed,
        "pending": pending,
        "high": high,
        "medium": medium,
        "low": low,
        "completion_rate": completion_rate
    })


# =========================================================
# GEMINI AI TASK ANALYZER
# =========================================================

@app.route("/ai-analyze", methods=["POST"])
def ai_analyze():

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    if not gemini_client:

        return jsonify({
            "success": False,
            "message": "Gemini AI is not connected."
        }), 500

    data = request.get_json()

    task_text = data.get("task", "").strip()

    if not task_text:

        return jsonify({
            "success": False,
            "message": "Please enter a task."
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

        ai_response = response.text

        return jsonify({
            "success": True,
            "ai_response": ai_response
        })

    except Exception as error:

        print("Gemini error:", error)

        return jsonify({
            "success": False,
            "message": "Gemini AI could not process the task.",
            "error": str(error)
        }), 500


# =========================================================
# GEMINI AI DAILY PLANNER
# =========================================================

@app.route("/ai-daily-plan", methods=["GET"])
def ai_daily_plan():

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    if not gemini_client:

        return jsonify({
            "success": False,
            "message": "Gemini AI is not connected."
        }), 500

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, task, deadline, priority
        FROM tasks
        WHERE user_id = ?
        AND completed = 0
        ORDER BY deadline ASC
    """, (user_id,))

    tasks = [dict(row) for row in cursor.fetchall()]

    connection.close()

    if not tasks:

        return jsonify({
            "success": True,
            "plan": "You currently have no pending tasks."
        })

    task_text = ""

    for index, task in enumerate(tasks, start=1):

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
            "plan": response.text
        })

    except Exception as error:

        print("Gemini planner error:", error)

        return jsonify({
            "success": False,
            "message": "Gemini could not create the daily plan.",
            "error": str(error)
        }), 500


# =========================================================
# GEMINI PRODUCTIVITY COACH
# =========================================================

@app.route("/ai-coach", methods=["POST"])
def ai_coach():

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    if not gemini_client:

        return jsonify({
            "success": False,
            "message": "Gemini AI is not connected."
        }), 500

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT task, deadline, priority, completed
        FROM tasks
        WHERE user_id = ?
    """, (user_id,))

    tasks = [dict(row) for row in cursor.fetchall()]

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
            "coach": response.text
        })

    except Exception as error:

        print("Gemini coach error:", error)

        return jsonify({
            "success": False,
            "message": "AI coach could not respond.",
            "error": str(error)
        }), 500


# =========================================================
# OLD DAILY PLAN COMPATIBILITY ROUTE
# =========================================================

@app.route("/daily-plan")
def daily_plan():

    user_id = get_logged_in_user()

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
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
    """, (user_id,))

    tasks = [dict(row) for row in cursor.fetchall()]

    connection.close()

    return jsonify({
        "success": True,
        "plan": tasks
    })



# =========================================================
# DOCUMENT ANALYZER API + KNOWLEDGE VAULT
# =========================================================

@app.route("/document-analyze", methods=["POST"])
def document_analyze():

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    if not gemini_client:
        return jsonify({
            "success": False,
            "message": "Gemini AI is not connected."
        }), 503

    uploaded_file = request.files.get("document")

    if not uploaded_file or not uploaded_file.filename:
        return jsonify({
            "success": False,
            "message": "Please select a TXT, PDF or DOCX file."
        }), 400

    mode = str(
        request.form.get("mode", "summary")
    ).strip().lower()

    mode_instructions = {
        "summary":
            "Give a clear summary with 5-10 key points.",
        "study":
            "Turn the document into study notes with important concepts, definitions and revision points.",
        "questions":
            "Create 8 useful exam or discussion questions with concise answers based only on the document.",
        "explain":
            "Explain the document in simple language for a college student."
    }

    instruction = mode_instructions.get(
        mode,
        mode_instructions["summary"]
    )

    try:

        filename, document_text = _extract_document_text(
            uploaded_file
        )

        prompt = f"""
You are a document analysis assistant.

Analyze ONLY the supplied document text.

Task:
{instruction}

Document filename:
{filename}

DOCUMENT TEXT:
{document_text}

Rules:
1. Do not invent facts that are not supported by the document.
2. Keep the answer organized with headings and bullets.
3. If the text is incomplete or unclear, say so.
4. Do not claim to have seen images, tables or pages whose text was not extracted.
"""

        models = [
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash"
        ]

        last_error = None

        for model_name in models:

            for attempt in range(2):

                try:

                    response = gemini_client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )

                    analysis = (
                        response.text or ""
                    ).strip()

                    if not analysis:
                        raise RuntimeError(
                            "Gemini returned an empty response."
                        )

                    connection = get_connection()
                    cursor = connection.cursor()

                    cursor.execute("""
                        INSERT INTO documents
                        (
                            user_id,
                            filename,
                            file_type,
                            content,
                            analysis
                        )
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        filename,
                        os.path.splitext(filename)[1].lower(),
                        document_text,
                        analysis
                    ))

                    document_id = cursor.lastrowid

                    connection.commit()
                    connection.close()

                    return jsonify({
                        "success": True,
                        "document_id": document_id,
                        "filename": filename,
                        "file_type":
                            os.path.splitext(
                                filename
                            )[1].lower(),
                        "mode": mode,
                        "analysis": analysis,
                        "reply": analysis
                    })

                except Exception as error:

                    last_error = error

                    error_text = str(error)

                    print(
                        f"Document analyzer error with "
                        f"{model_name} "
                        f"(attempt {attempt + 1}/2): "
                        f"{error_text}"
                    )

                    if (
                        (
                            "503" in error_text
                            or "UNAVAILABLE" in error_text
                        )
                        and attempt == 0
                    ):

                        time.sleep(2)
                        continue

                    break

        return jsonify({
            "success": False,
            "message":
                "Document analysis is temporarily unavailable. "
                "Please try again.",
            "error":
                str(last_error)
                if last_error
                else "Unknown Gemini error"
        }), 503

    except ValueError as error:

        return jsonify({
            "success": False,
            "message": str(error)
        }), 400

    except Exception as error:

        print(
            "Document analyzer error:",
            error
        )

        return jsonify({
            "success": False,
            "message":
                "Could not analyze this document.",
            "error": str(error)
        }), 500


# =========================================================
# KNOWLEDGE VAULT - LIST DOCUMENTS
# =========================================================

@app.route("/knowledge-vault", methods=["GET"])
def knowledge_vault():

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            filename,
            file_type,
            analysis,
            created_at
        FROM documents
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))

    documents = [
        dict(row)
        for row in cursor.fetchall()
    ]

    connection.close()

    return jsonify({
        "success": True,
        "documents": documents
    })


# =========================================================
# KNOWLEDGE VAULT - GET ONE DOCUMENT
# =========================================================

@app.route(
    "/knowledge-vault/<int:document_id>",
    methods=["GET"]
)
def get_vault_document(document_id):

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            filename,
            file_type,
            content,
            analysis,
            created_at
        FROM documents
        WHERE id = ?
        AND user_id = ?
    """, (
        document_id,
        user_id
    ))

    document = cursor.fetchone()

    connection.close()

    if not document:
        return jsonify({
            "success": False,
            "message": "Document not found."
        }), 404

    return jsonify({
        "success": True,
        "document": dict(document)
    })


# =========================================================
# KNOWLEDGE VAULT - DELETE DOCUMENT
# =========================================================

@app.route(
    "/knowledge-vault/<int:document_id>",
    methods=["DELETE"]
)
def delete_vault_document(document_id):

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM documents
        WHERE id = ?
        AND user_id = ?
    """, (
        document_id,
        user_id
    ))

    deleted_count = cursor.rowcount

    connection.commit()
    connection.close()

    if deleted_count == 0:
        return jsonify({
            "success": False,
            "message": "Document not found."
        }), 404

    return jsonify({
        "success": True,
        "message": "Document removed from Knowledge Vault."
    })


# =========================================================
# KNOWLEDGE VAULT - ASK A QUESTION
# =========================================================

@app.route(
    "/knowledge-vault/ask",
    methods=["POST"]
)
def ask_knowledge_vault():

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    if not gemini_client:
        return jsonify({
            "success": False,
            "message": "Gemini AI is not connected."
        }), 503

    data = request.get_json(
        silent=True
    ) or {}

    question = str(
        data.get("question", "")
    ).strip()

    document_id = data.get(
        "document_id"
    )

    if not question:
        return jsonify({
            "success": False,
            "message": "Please enter a question."
        }), 400

    connection = get_connection()
    cursor = connection.cursor()

    if document_id:

        try:
            document_id = int(document_id)
        except (TypeError, ValueError):

            connection.close()

            return jsonify({
                "success": False,
                "message": "Invalid document ID."
            }), 400

        cursor.execute("""
            SELECT
                id,
                filename,
                content
            FROM documents
            WHERE id = ?
            AND user_id = ?
        """, (
            document_id,
            user_id
        ))

        documents = cursor.fetchall()

    else:

        cursor.execute("""
            SELECT
                id,
                filename,
                content
            FROM documents
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, (user_id,))

        documents = cursor.fetchall()

    connection.close()

    if not documents:

        return jsonify({
            "success": False,
            "message":
                "Your Knowledge Vault is empty. "
                "Upload a document first."
        }), 404

    context_parts = []

    total_chars = 0
    max_context_chars = 30000

    for document in documents:

        remaining = (
            max_context_chars
            - total_chars
        )

        if remaining <= 0:
            break

        content = document["content"][:remaining]

        context_parts.append(
            f"\n--- DOCUMENT: "
            f"{document['filename']} ---\n"
            f"{content}\n"
        )

        total_chars += len(content)

    knowledge_context = "".join(
        context_parts
    )

    prompt = f"""
You are the Knowledge Vault assistant.

Answer the user's question using ONLY
the document content supplied below.

USER QUESTION:
{question}

DOCUMENT KNOWLEDGE:
{knowledge_context}

Rules:
1. Use only the supplied documents.
2. Do not invent facts.
3. If the answer is not present, clearly say:
   "I could not find that information in your Knowledge Vault."
4. Mention the relevant document filename when useful.
5. Keep the answer clear and concise.
"""

    models = [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash"
    ]

    last_error = None

    for model_name in models:

        for attempt in range(2):

            try:

                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )

                answer = (
                    response.text or ""
                ).strip()

                if not answer:
                    raise RuntimeError(
                        "Gemini returned an empty response."
                    )

                return jsonify({
                    "success": True,
                    "answer": answer
                })

            except Exception as error:

                last_error = error

                error_text = str(error)

                print(
                    f"Knowledge Vault error with "
                    f"{model_name} "
                    f"(attempt {attempt + 1}/2): "
                    f"{error_text}"
                )

                if (
                    (
                        "503" in error_text
                        or "UNAVAILABLE" in error_text
                    )
                    and attempt == 0
                ):

                    time.sleep(2)
                    continue

                break

    return jsonify({
        "success": False,
        "message":
            "Knowledge Vault is temporarily unavailable. "
            "Please try again.",
        "error":
            str(last_error)
            if last_error
            else "Unknown Gemini error"
    }), 503


# =========================================================
# AI LIFE & STUDY COPILOT
# =========================================================

@app.route("/copilot-chat", methods=["POST"])
def copilot_chat():

    user_id = get_logged_in_user()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    if not gemini_client:
        return jsonify({
            "success": False,
            "message": "Gemini AI is not connected."
        }), 500

    data = request.get_json(silent=True) or {}

    user_message = str(data.get("message", "")).strip()
    tool = str(data.get("tool", "General Copilot")).strip()

    if not user_message:
        return jsonify({
            "success": False,
            "message": "Please enter a message."
        }), 400

    # Use the user's existing task data as lightweight context.
    # This does not modify the tasks table or any existing task routes.
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT task, deadline, priority, completed
        FROM tasks
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 20
    """, (user_id,))

    tasks = [dict(row) for row in cursor.fetchall()]
    connection.close()

    task_context = "\n".join(
        f"- {task['task']} | deadline: {task['deadline'] or 'None'} | "
        f"priority: {task['priority'] or 'MEDIUM'} | "
        f"completed: {'Yes' if task['completed'] else 'No'}"
        for task in tasks
    )

    if not task_context:
        task_context = "No tasks are currently available."

    tool_instructions = {
        "Study Buddy":
            "Teach clearly using simple explanations, examples, short revision points, and exam-focused guidance.",
        "Writing Assistant":
            "Help improve writing, structure, grammar, clarity, tone, assignments, reports, and emails.",
        "Presentation Coach":
            "Help with presentation structure, speaking practice, confidence, timing, and concise delivery.",
        "Coding Buddy":
            "Explain code and errors step by step. Prefer beginner-friendly solutions and safe code.",
        "Document Analyzer":
            "Help the user understand documents they provide. If no document content is provided, clearly say that and help with the question using the available context.",
        "Research Assistant":
            "Help organize research questions, topics, outlines, keywords, and evidence-aware next steps. Do not invent sources.",
        "Idea Generator":
            "Generate practical, original ideas for projects, presentations, innovation, and problem solving.",
        "Knowledge Vault":
            "Help organize and recall information the user shares in the conversation. Do not claim to remember information that was not provided.",
        "Problem Solver":
            "Break problems into small logical steps and explain the reasoning clearly.",
        "General Copilot":
            "Act as a helpful general-purpose study and productivity assistant."
    }

    instructions = tool_instructions.get(
        tool,
        tool_instructions["General Copilot"]
    )

    prompt = f"""
You are the AI Life & Study Copilot inside a student's productivity application.

Current Copilot mode: {tool}

Mode instructions:
{instructions}

The student's current task context is:
{task_context}

User's message:
{user_message}

Rules:
1. Answer the user's actual question first.
2. Be concise but useful.
3. Use simple language suitable for a college student.
4. If the question is academic, explain step by step when useful.
5. If the user asks about their tasks, use the task context above.
6. Never invent deadlines, tasks, documents, personal facts, or sources.
7. Do not claim to have analyzed a document unless document content was actually supplied.
8. Do not change, delete, complete, or create tasks from this chat.
9. If information is missing, say what is missing and still provide useful guidance.
"""

    # Gemini can temporarily return 503 when a model is overloaded.
    # Retry briefly, then fall back to another current Flash model.
    # This keeps a temporary Gemini capacity issue from becoming a generic
    # Copilot 500 error.
    copilot_models = [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash"
    ]

    last_error = None

    for model_name in copilot_models:
        for attempt in range(2):
            try:
                print(
                    f"🤖 Copilot request using {model_name} "
                    f"(attempt {attempt + 1}/2)"
                )

                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )

                reply = (response.text or "").strip()

                if not reply:
                    raise RuntimeError("Gemini returned an empty response.")

                return jsonify({
                    "success": True,
                    "reply": reply,
                    "tool": tool
                })

            except Exception as error:
                last_error = error
                error_text = str(error)
                print(
                    f"Gemini Copilot error with {model_name} "
                    f"(attempt {attempt + 1}/2): {error_text}"
                )

                # Retry only temporary capacity/service failures.
                if "503" in error_text or "UNAVAILABLE" in error_text:
                    if attempt == 0:
                        time.sleep(2)
                        continue

                # For non-503 errors, move directly to the next model.
                break

    print("❌ All Copilot Gemini models failed:", last_error)

    return jsonify({
        "success": False,
        "message": (
            "Copilot is temporarily unavailable. "
            "Please try again in a moment."
        ),
        "error": str(last_error) if last_error else "Unknown Gemini error"
    }), 503


# =========================================================
# REMINDER WORKER
# =========================================================

reminded_tasks = set()


def reminder_worker():

    print("⏰ Reminder system started.")

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

                reminder_time = deadline - timedelta(minutes=5)

                key = f"{task['user_id']}_{task['id']}"

                if now >= reminder_time and now <= deadline:

                    if key not in reminded_tasks:

                        print(
                            f"🔔 Reminder: {task['task']}"
                        )

                        if WINOTIFY_AVAILABLE:

                            try:

                                toast = Notification(
                                    app_id="AI Productivity Agent",
                                    title="Task Reminder",
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

                        reminded_tasks.add(key)

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

    create_tables()

    reminder_thread = threading.Thread(
        target=reminder_worker,
        daemon=True
    )

    reminder_thread.start()

    print("")
    print("========================================")
    print("🚀 AI PRODUCTIVITY AGENT")
    print("========================================")
    print("🌐 Backend: http://127.0.0.1:5000")

    if gemini_client:
        print("🤖 Gemini AI: Connected")
    else:
        print("🤖 Gemini AI: Not Connected")

    print("⏰ Reminder System: Running")
    print("========================================")
    print("")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )
