import time
from datetime import datetime

print("🔔 AI TASK REMINDER")
print("=" * 40)

task = input("Enter your task: ")
reminder_time = input("Enter reminder time (HH:MM): ")

print("\n✅ Reminder set successfully!")
print(f"📌 Task: {task}")
print(f"⏰ Reminder: {reminder_time}")

while True:
    current_time = datetime.now().strftime("%H:%M")

    if current_time == reminder_time:
        print("\n🔔🔔 REMINDER 🔔🔔")
        print(f"📌 TASK: {task}")
        print("⚠️ Please complete your task!")
        break

    time.sleep(30)