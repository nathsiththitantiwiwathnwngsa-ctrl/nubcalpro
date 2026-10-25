import os
import json
import requests
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    ReplyMessageRequest, TextMessage, 
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from google import genai
from dotenv import load_dotenv
import sheet_service

load_dotenv()
app = FastAPI()

channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
channel_secret = os.getenv("LINE_CHANNEL_SECRET")

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# เก็บข้อมูลโปรไฟล์และแคลอรีสะสมรายวันของผู้ใช้
USER_PROFILES = {}

# ฟังก์ชันวิเคราะห์อาหารจากข้อความ
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
        model='gemini-3.8-flash',
        contents=prompt,
    )
    cleaned_json = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned_json)

# ฟังก์ชันวิเคราะห์อาหารจากรูปภาพ
def analyze_food_image(image_bytes):
    prompt = """
    คุณคือผู้เชี่ยวชาญด้านโภชนาการ ช่วยดูรูปอาหารนี้แล้ววิเคราะห์ว่าคือเมนูอะไร พร้อมประเมินสารอาหารโดยประมาณ 
    ตอบกลับในรูปแบบ JSON เท่านั้น โดยมีโครงสร้างดังนี้:
    {
      "food_name": "ชื่ออาหารในรูปสั้นๆ",
      "calories": 500,
      "protein": 30,
      "carbs": 50,
      "fat": 20
    }
    """
    response = client.models.generate_content(
        model='gemini-3.8-flash',
        contents=[
            genai.types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
            prompt
        ],
    )
    cleaned_json = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned_json)

def get_line_user_name(user_id):
    url = f"https://api.line.me/v2/bot/profile/{user_id}"
    headers = {"Authorization": f"Bearer {channel_access_token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("displayName", "Unknown User")
    return "Unknown User"

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        handler.handle(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"

# 1. จัดการข้อความตัวหนังสือปกติ
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id
    user_name = get_line_user_name(user_id)
    
    if user_text.lower() in ["เมนู", "menu", "เริ่มต้น", "start", "สวัสดี", "hi"]:
        quick_reply_menu = QuickReply(
            items=[
                QuickReplyItem(action=MessageAction(label="🎯 ตั้งค่าโปรแกรม/เป้าหมาย", text="ตั้งเป้าหมาย")),
                QuickReplyItem(action=MessageAction(label="📊 เช็กโควตาคงเหลือ", text="เช็กโควตา")),
                QuickReplyItem(action=MessageAction(label="💧 เตือนดื่มน้ำ", text="ดื่มน้ำหน่อย")),
            ]
        )
        reply_text = f"สวัสดีครับคุณ {user_name} 👋\nเลือกเมนูที่ต้องการด้านล่างได้เลยครับ หรือจะ **ส่งรูปถ่ายอาหาร** มาให้บอทคำนวณก็ได้นะ!"
        send_reply(event.reply_token, reply_text, quick_reply_menu)
        return

    if user_text == "ตั้งเป้าหมาย":
        sample_text = (
            "📝 วิธีตั้งค่าโปรแกรมของคุณ:\n"
            "พิมพ์ตามรูปแบบนี้ได้เลยครับ:\n\n"
            "👉 เซ็ตเป้าหมาย น้ำหนัก 70 ส่วนสูง 175 อายุ 19 โหมด ลดไขมัน\n"
            "(เลือกโหมด: ลดไขมัน / เพิ่มน้ำหนัก / คงน้ำหนัก)"
        )
        send_reply(event.reply_token, sample_text)
        return

    if user_text.startswith("เซ็ตเป้าหมาย"):
        try:
            parts = user_text.split()
            weight = float(parts[2])
            height = float(parts[4])
            age = int(parts[6])
            mode = parts[8]
            
            bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
            tdee = int(bmr * 1.55)
            
            if "ลด" in mode:
                target_calories = tdee - 500
                mode_name = "🔥 ลดไขมัน (-500 kcal จาก TDEE)"
            elif "เพิ่ม" in mode:
                target_calories = tdee + 500
                mode_name = "📈 เพิ่มน้ำหนัก (+500 kcal จาก TDEE)"
            else:
                target_calories = tdee
                mode_name = "⚖️ คงน้ำหนัก (เท่ากับ TDEE)"
                
            USER_PROFILES[user_id] = {
                "weight": weight, "height": height, "tdee": tdee,
                "target": target_calories, "consumed": 0, "mode": mode_name
            }
            
            reply_text = (
                f"✅ บันทึกโปรแกรมสำเร็จ!\n👤 โหมด: {mode_name}\n"
                f"⚡ TDEE: {tdee} kcal\n🎯 เป้าหมายต่อวัน: {target_calories} kcal"
            )
            send_reply(event.reply_token, reply_text)
        except Exception:
            send_reply(event.reply_token, "⚠️ รูปแบบไม่ถูกต้อง ลองพิมพ์ใหม่อีกครั้งตามตัวอย่าง")
        return

    if user_text == "เช็กโควตา":
        profile = USER_PROFILES.get(user_id)
        if not profile:
            send_reply(event.reply_token, "⚠️ ยังไม่ได้ตั้งเป้าหมาย พิมพ์ 'ตั้งเป้าหมาย' เพื่อเริ่มเซ็ตระบบก่อนครับ!")
            return
            
        remaining = profile["target"] - profile["consumed"]
        reply_text = (
            f"📊 สรุปโควตาของคุณวันนี้ ({user_name}):\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 โปรแกรม: {profile['mode']}\n"
            f"🎯 เป้าหมาย: {profile['target']} kcal\n"
            f"🔥 กินไปแล้ว: {profile['consumed']} kcal\n"
            f"🔋 โควตาคงเหลือ: {remaining} kcal"
        )
        send_reply(event.reply_token, reply_text)
        return

    if user_text == "ดื่มน้ำหน่อย":
        send_reply(event.reply_token, "💧 แจ้งเตือน: ได้เวลาจิบน้ำสะอาด 1 แก้วแล้วครับคุณมาร์ค! รักษาความชุ่มชื้นให้กล้ามเนื้อกัน 💪")
        return

    # บันทึกอาหารจากข้อความ
    try:
        nutrition = analyze_food_text(user_text)
        sheet_service.log_food_data(user_name, nutrition)
        
        quota_text = update_user_calories(user_id, nutrition["calories"])
        reply_text = format_nutrition_reply(user_name, nutrition, quota_text)
        send_reply(event.reply_token, reply_text)
    except Exception as e:
        print(f"🔥 Error: {e}")
        send_reply(event.reply_token, "⚠️ เกิดข้อผิดพลาด ลองใหม่อีกครั้งนะครับ")

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    user_id = event.source.user_id
    user_name = get_line_user_name(user_id)
    
    try:
        message_id = event.message.id
        
        # ใช้ requests ดึงไฟล์รูปจาก LINE API ตรงๆ ผ่าน Messaging API endpoint
        url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
        headers = {"Authorization": f"Bearer {channel_access_token}"}
        
        image_response = requests.get(url, headers=headers)
        if image_response.status_code == 200:
            image_bytes = image_response.content
        else:
            raise Exception(f"Failed to download image, status code: {image_response.status_code}")

        # ส่งรูปให้ Gemini วิเคราะห์
        nutrition = analyze_food_image(image_bytes)
        sheet_service.log_food_data(user_name, nutrition)
        
        quota_text = update_user_calories(user_id, nutrition["calories"])
        reply_text = format_nutrition_reply(user_name, nutrition, quota_text)
        send_reply(event.reply_token, reply_text)
        
    except Exception as e:
        print(f"🔥 Image Error: {e}")
        send_reply(event.reply_token, "⚠️ ไม่สามารถวิเคราะห์รูปภาพนี้ได้ ลองส่งรูปใหม่อีกครั้ง หรือพิมพ์ชื่ออาหารแทนได้ครับ")

# ฟังก์ชันช่วยคำนวณโควตาแคลอรีสะสม
def update_user_calories(user_id, meal_calories):
    if user_id in USER_PROFILES:
        USER_PROFILES[user_id]["consumed"] += meal_calories
        target = USER_PROFILES[user_id]["target"]
        consumed = USER_PROFILES[user_id]["consumed"]
        remaining = target - consumed
        return f"\n━━━━━━━━━━━━━━━━━━\n🎯 เป้าหมาย: {target} kcal\n🔋 เหลือโควตา: {remaining} kcal"
    return "\n💡 (ยังไม่ได้ตั้งเป้าหมาย พิมพ์ 'ตั้งเป้าหมาย' เพื่อคำนวณโควตาได้ครับ)"

# จัดหน้าตาข้อความตอบกลับ
def format_nutrition_reply(user_name, nutrition, quota_text):
    return (
        f"✅ บันทึกให้แล้วครับ ({user_name})!\n"
        f"🍽️ {nutrition['food_name']}\n"
        f"🔥 แคลอรีมื้อนี้: {nutrition['calories']} kcal\n"
        f"🥩 โปรตีน: {nutrition['protein']} g | 🍚 คาร์บ: {nutrition['carbs']} g | 🥑 ไขมัน: {nutrition['fat']} g"
        f"{quota_text}"
    )

def send_reply(reply_token, text, quick_reply=None):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text, quick_reply=quick_reply)]
            )
        )