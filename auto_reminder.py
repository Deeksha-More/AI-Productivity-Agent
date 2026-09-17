from datetime import datetime
import time
import os
import winsound
from winotify import Notification, audio

TASKS_FILE = "tasks.txt"

print("🔔 AI MEETING ASSISTANT - SMART REMINDER")
print("=" * 55)


def load_tasks():
    """Read tasks created by the Flask website."""

    if not os.path.exists(TASKS_FILE):
        return []

    tasks = []

    with open(TASKS_FILE, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            parts = line.split("|")

            task = parts[0] if len(parts) > 0 else ""
            deadline = parts[1] if len(parts) > 1 else "Not specified"
            priority = parts[2] if len(parts) > 2 else "MEDIUM"
            snooze_until = parts[3] if len(parts) > 3 else ""

            tasks.append({
                "task": task,
                "deadline": deadline,
                "priority": priority,
                "snooze_until": snooze_until
            })

    return tasks


def play_sound():
    """Play a built-in Windows sound."""

    try:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        print("🔊 Windows reminder sound played!")
    except Exception as error:
        print(f"⚠️ Sound error: {error}")


def send_notification(task):
    """Show Windows notification with sound."""

    notification = Notification(
        app_id="AI Meeting Assistant",
        title="🔔 AI Task Reminder",
        msg=(
            f"{task['task']}\n"
            f"Deadline: {task['deadline']}\n"
            f"Priority: {task['priority']}"
        ),
        duration="long"
    )

    notification.set_audio(
        audio.Default,
        loop=False
    )

    notification.show()

    # Extra Windows sound
    play_sound()

    print("✅ Notification sent!")


def get_due_tasks():
    """Find tasks whose deadline has arrived."""

    tasks = load_tasks()
    due_tasks = []

    now = datetime.now()

    for task in tasks:

        deadline = task["deadline"]

        if deadline == "Not specified":
            continue

        try:
            deadline_time = datetime.strptime(
                deadline,
                "%Y-%m-%d %H:%M"
            )

            # Check snooze
            if task["snooze_until"]:
                try:
                    snooze_time = datetime.strptime(
                        task["snooze_until"],
                        "%Y-%m-%d %H:%M"
                    )

                    if now < snooze_time:
                        continue

                except ValueError:
                    pass

            if now >= deadline_time:
                due_tasks.append(task)

        except ValueError:
            continue

    return due_tasks


print("\n📋 Reminder system started.")
print("🔊 Windows sound is enabled.")
print("😴 Snooze is supported.")
print("\n⏳ Waiting for tasks...\n")


already_notified = set()

while True:

    try:

        due_tasks = get_due_tasks()

        for task in due_tasks:

            task_key = (
                task["task"],
                task["deadline"]
            )

            if task_key in already_notified:
                continue

            print("\n" + "=" * 55)
            print("🔔 TASK REMINDER")
            print("=" * 55)

            print(f"📌 Task: {task['task']}")
            print(f"⏰ Deadline: {task['deadline']}")
            print(f"⭐ Priority: {task['priority']}")

            send_notification(task)

            already_notified.add(task_key)

            print("=" * 55)

        time.sleep(5)

    except KeyboardInterrupt:

        print("\n🛑 Reminder system stopped.")
        break

    except Exception as error:

        print(f"\n⚠️ Reminder error: {error}")
        time.sleep(5)