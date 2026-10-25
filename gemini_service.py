import os
import json
from google import genai
from dotenv import load_dotenv

load_dotenv()


client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def analyze_food_text(user_text):
    prompt = f"""
    คุณคือผู้เชี่ยวชาญด้านโภชนาการ วิเคราะห์อาหารที่ได้รับและตอบกลับในรูปแบบ JSON เท่านั้น โดยมีโครงสร้างดังนี้:
    {{
      "food_name": "ชื่ออาหารสรุปสั้นๆ",
      "calories": 200,
      "protein": 30,
      "carbs": 10,
      "fat": 5
    }}
    
    ข้อความอาหาร: {user_text}
    """
    
    response = client.models.generate_content(
        model='gemini-1.5-flash',
        contents=prompt,
    )
    
    cleaned_json = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned_json)