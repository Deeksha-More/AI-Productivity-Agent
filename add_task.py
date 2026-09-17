from datetime import datetime
import os

print("📋 AI MEETING ASSISTANT")
print("=" * 45)

print("\n➕ ADD YOUR OWN TASK")

person = input("👤 Enter your name: ")
task = input("📌 Enter your task: ")
deadline = input("⏰ Enter deadline: ")

# Save task
with open("tasks.txt", "a", encoding="utf-8") as file:
    file.write(f"Person: {person}\n")
    file.write(f"Task: {task}\n")
    file.write(f"Deadline: {deadline}\n")
    file.write("-" * 40 + "\n")

print("\n✅ Task added successfully!")
print(f"👤 Person: {person}")
print(f"📌 Task: {task}")
print(f"⏰ Deadline: {deadline}")
print("\n💾 Task saved to tasks.txt")