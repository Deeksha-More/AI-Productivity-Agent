from dotenv import load_dotenv
import os
import threading
import time
from datetime import datetime, timedelta

from google import genai
from winotify import Notification, audio


# ==============================
# LOAD GEMINI API
# ==============================

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ Gemini API key not found!")
    exit()

client = genai.Client(api_key=api_key)


# ==============================
# ADD TASK
# ==============================

def add_my_task():

    print("\n➕ ADD MY TASK")
    print("=" * 40)

    user_input = input("📌 Enter your task with deadline:\n")

    # Current date and time
    now = datetime.now()

    today = now.strftime("%d-%m-%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d-%m-%Y")
    day_after_tomorrow = (now + timedelta(days=2)).strftime("%d-%m-%Y")

    prompt = f"""
You are a task management assistant.

Current date: {today}
Current time: {now.strftime("%H:%M")}

Understand the user's task:

{user_input}

Return ONLY:

TASK: <task>
DATE_WORD: <today/tomorrow/day_after_tomorrow/exact date/Not specified>
TIME: <time in 24-hour HH:MM format>

Rules:
- If user says today, return DATE_WORD: today
- If user says tomorrow, return DATE_WORD: tomorrow
- If user says day after tomorrow, return DATE_WORD: day_after_tomorrow
- If user gives an exact date, return that date.
- Convert time to 24-hour HH:MM.
- Do not invent information.
- If date is missing, return DATE_WORD: Not specified.
- If time is missing, return TIME: Not specified.
"""

    try:

        chat = client.chats.create(
            model="gemini-3.6-flash"
        )

        response = chat.send_message(prompt)

        result = response.text.strip()

        print("\n🤖 AI UNDERSTOOD:")
        print("=" * 40)
        print(result)

        # ------------------------------
        # Extract AI result
        # ------------------------------

        task = "Task"
        date_word = "Not specified"
        task_time = "Not specified"

        for line in result.splitlines():

            line = line.strip()

            if line.startswith("TASK:"):
                task = line.replace("TASK:", "").strip()

            elif line.startswith("DATE_WORD:"):
                date_word = line.replace("DATE_WORD:", "").strip()

            elif line.startswith("TIME:"):
                task_time = line.replace("TIME:", "").strip()

        # ------------------------------
        # Convert date
        # ------------------------------

        date_word_lower = date_word.lower()

        if date_word_lower == "today":

            final_date = today

        elif date_word_lower == "tomorrow":

            final_date = tomorrow

        elif date_word_lower == "day_after_tomorrow":

            final_date = day_after_tomorrow

        elif date_word_lower == "not specified":

            final_date = "Not specified"

        else:

            final_date = date_word

        # ------------------------------
        # Save task
        # ------------------------------

        with open("smart_tasks.txt", "a", encoding="utf-8") as file:

            file.write(f"TASK: {task}\n")
            file.write(f"DATE: {final_date}\n")
            file.write(f"TIME: {task_time}\n")
            file.write("-" * 40 + "\n")

        print("\n💾 Task saved successfully!")

        print(f"📌 Task: {task}")
        print(f"📅 Date: {final_date}")
        print(f"⏰ Time: {task_time}")

        # Start reminder
        start_reminder(task, final_date, task_time)

    except Exception as e:

        print("\n❌ ERROR:")
        print(e)


# ==============================
# START REMINDER
# ==============================

def start_reminder(task, date, task_time):

    if date == "Not specified" or task_time == "Not specified":

        print("\n⚠️ Reminder cannot be scheduled.")
        print("Please provide both date and time.")

        return

    try:

        reminder_datetime = datetime.strptime(
            f"{date} {task_time}",
            "%d-%m-%Y %H:%M"
        )

        current_datetime = datetime.now()

        if reminder_datetime <= current_datetime:

            print("\n⚠️ This deadline has already passed.")

            return

        wait_seconds = (
            reminder_datetime - current_datetime
        ).total_seconds()

        print("\n🔔 REMINDER SCHEDULED")
        print("=" * 40)

        print(f"📌 Task: {task}")
        print(f"📅 Date: {date}")
        print(f"⏰ Time: {task_time}")

        reminder_thread = threading.Thread(
            target=reminder_worker,
            args=(task, date, task_time, wait_seconds),
            daemon=True
        )

        reminder_thread.start()

        print("⏳ Waiting for reminder...")

    except ValueError:

        print("\n❌ Invalid date or time format.")
        print("Expected format:")
        print("DD-MM-YYYY HH:MM")


# ==============================
# REMINDER WORKER
# ==============================

def reminder_worker(task, date, task_time, wait_seconds):

    time.sleep(wait_seconds)

    print("\n")
    print("=" * 50)
    print("🔔🔔 TASK REMINDER 🔔🔔")
    print("=" * 50)

    print(f"📌 Task: {task}")
    print(f"📅 Date: {date}")
    print(f"⏰ Time: {task_time}")

    # Windows notification
    notification = Notification(
        app_id="AI Meeting & Task Assistant",
        title="🔔 AI Task Reminder",
        msg=f"{task}\nDeadline: {date} {task_time}",
        duration="long"
    )

    # 🔊 Notification sound
    notification.set_audio(
        audio.Default,
        loop=False
    )

    notification.show()

    print("\n✅ Windows notification sent!")
    print("🔊 Reminder sound played!")


# ==============================
# SHOW TASKS
# ==============================

def show_tasks():

    print("\n📋 MY TASKS")
    print("=" * 40)

    if not os.path.exists("smart_tasks.txt"):

        print("No tasks found.")

        return

    with open("smart_tasks.txt", "r", encoding="utf-8") as file:

        print(file.read())


# ==============================
# MAIN MENU
# ==============================

while True:

    print("\n")
    print("🤖 AI MEETING & TASK ASSISTANT")
    print("=" * 45)

    print("1. ➕ Add My Task")
    print("2. 📋 View My Tasks")
    print("3. ❌ Exit")

    choice = input("\nChoose an option: ")

    if choice == "1":

        add_my_task()

    elif choice == "2":

        show_tasks()

    elif choice == "3":

        print("\n👋 Thank you for using AI Assistant!")

        break

    else:

        print("\n❌ Invalid option. Please choose 1, 2 or 3.")