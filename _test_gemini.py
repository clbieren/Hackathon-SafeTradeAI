"""Geçici Gemini canlı test scripti — doğrulama sonrası silinebilir."""
import asyncio

# .env'i oku
with open("c:/Users/clbie/Desktop/Pide_Idle/While-Lose-Hackathon/Eren/.env", "r", encoding="utf-8-sig") as f:
    lines = f.read().splitlines()

keys = {}
for line in lines:
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        keys[k.strip()] = v.strip()

gemini_key = keys.get("GEMINI_API_KEY", "")
print(f"Key found: {bool(gemini_key)} | prefix: {gemini_key[:15]}...")

from google import genai
from google.genai import types as genai_types
import json


async def raw_test():
    client = genai.Client(api_key=gemini_key)

    prompt = (
        "Bir finans analistinin gözünden Apple Inc. şirketini değerlendir. "
        "Şirket çok büyük, karlı ve stabil. "
        "Şu JSON formatında yanıt ver: "
        '{"score": <int 0-100>, "summary": "<str>", "risk_level": "<Low|Medium|High>"}'
    )

    response = await client.aio.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=256,
        ),
    )
    print("Raw:", response.text[:300])
    parsed = json.loads(response.text)
    print(f"score={parsed['score']} | risk={parsed['risk_level']}")
    print(f"summary: {parsed['summary'][:120]}")


asyncio.run(raw_test())
