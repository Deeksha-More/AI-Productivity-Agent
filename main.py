from dotenv import load_dotenv
import os
import re
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ Gemini API key not found!")
    exit()

print("✅ API key found!")

client = genai.Client(api_key=api_key)

# Read meeting transcript
with open("meeting_transcript.txt", "r", encoding="utf-8") as file:
    transcript = file.read()

print("📄 Transcript loaded!")
print("🤖 Analyzing meeting...")

prompt = f"""
You are an intelligent AI Meeting Assistant.

Analyze the meeting transcript below.

Give the output in this exact format:

TASKS:
Person | Task | Deadline

SUMMARY:
Write a short meeting summary.

DECISIONS:
List the important decisions.

IMPORTANT:
- Do not invent information.
- If the person is unknown, write "Not specified".
- If the deadline is unknown, write "Not specified".

Meeting Transcript:
{transcript}
"""

try:
    chat = client.chats.create(
        model="gemini-3.6-flash"
    )

    response = chat.send_message(prompt)
    result = response.text

    print("\n🤖 AI MEETING ASSISTANT")
    print("=" * 50)
    print(result)

    # Extract TASKS section
    tasks_section = ""

    if "TASKS:" in result and "SUMMARY:" in result:
        tasks_section = result.split("TASKS:")[1].split("SUMMARY:")[0]

    print("\n📋 EXTRACTED TASKS")
    print("=" * 50)

    tasks = []

    for line in tasks_section.strip().splitlines():

        if "|" in line and not line.startswith("Person"):
            parts = [part.strip() for part in line.split("|")]

            if len(parts) == 3:
                person, task, deadline = parts

                tasks.append({
                    "person": person,
                    "task": task,
                    "deadline": deadline
                })

                print(f"👤 Person: {person}")
                print(f"📌 Task: {task}")
                print(f"⏰ Deadline: {deadline}")
                print("-" * 30)

    # Save extracted tasks
    with open("tasks.txt", "w", encoding="utf-8") as file:

        for task in tasks:
            file.write(f"Person: {task['person']}\n")
            file.write(f"Task: {task['task']}\n")
            file.write(f"Deadline: {task['deadline']}\n")
            file.write("-" * 40 + "\n")

    print("\n💾 Tasks saved to tasks.txt")
    print("✅ AI Meeting Assistant completed successfully!")

except Exception as e:
    print("\n❌ ERROR:")
    print(e)