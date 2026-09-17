from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=api_key)

print("Available Gemini models:")
print("=" * 50)

for model in client.models.list():
    print(model.name)