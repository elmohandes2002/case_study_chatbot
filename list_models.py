import os

import httpx
from dotenv import load_dotenv

load_dotenv()

response = httpx.get(
    "https://generativelanguage.googleapis.com/v1beta/models",
    params={"key": os.getenv("GEMINI_API_KEY"), "pageSize": 100},
)
for model in response.json().get("models", []):
    if "generateContent" in model.get("supportedGenerationMethods", []):
        print(model["name"].replace("models/", "gemini/"))