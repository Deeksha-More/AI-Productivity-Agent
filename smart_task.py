from dotenv import load_dotenv
import os
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ Gemini API key not found!")
    exit()

client = genai.Client(api_key=api_key)

print("🤖 SMART TASK ASSISTANT")
print("=" * 50)

user_input = input("\n📌 Enter your task with deadline:\n")

prompt = f"""
You are a task management assistant.

Understand the user's task and deadline.

User input:
{user_input}

Return ONLY this format:

TASK: <task>
DATE: <date in DD-MM-YYYY format>
TIME: <time in 24-hour HH:MM format>

Rules:
- Extract the task clearly.
- Convert the date into DD-MM-YYYY.
- Convert the time into 24-hour HH:MM.
- Do not invent a date or time.
- If date is missing, write: Not specified
- If time is missing, write: Not specified
"""

try:
    chat = client.chats.create(
        model="gemini-3.6-flash"
    )

    response = chat.send_message(prompt)

    print("\n🤖 AI UNDERSTOOD:")
    print("=" * 50)
    print(response.text)

except Exception as e:
    print("\n❌ ERROR:")
    print(e)