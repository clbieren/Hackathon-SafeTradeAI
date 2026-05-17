import asyncio
from app.services.ai_engine import AIService

async def test():
    svc = AIService()
    news_data = [{'title': 'Tesla sued for autopilot issues', 'description': 'Tesla faces a new lawsuit...'}]
    financial_data = {'marketCapitalization': 600000, 'finnhubIndustry': 'Automotive'}
    
    prompt = svc._build_prompt('Tesla', news_data, financial_data)
    
    from google import genai
    from google.genai import types as genai_types
    from app.config import get_settings
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    
    response = await client.aio.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type='application/json',
            temperature=0.2,
            max_output_tokens=1024
        )
    )
    
    print('FINISH REASON:', response.candidates[0].finish_reason)
    print('RAW TEXT:', repr(response.text))

asyncio.run(test())
