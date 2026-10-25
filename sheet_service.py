import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)


sheet = client.open("Nubcal-User").sheet1

def log_food_data(user_name, food_data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [
        now,
        user_name,  # บันทึกชื่อผู้ใช้แยกว่าใครเป็นคนกิน
        food_data.get("food_name"),
        food_data.get("calories"),
        food_data.get("protein"),
        food_data.get("carbs"),
        food_data.get("fat")
    ]
    sheet.append_row(row)