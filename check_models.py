import os
from dotenv import load_dotenv
from google import genai

# 1. Load API Key từ file .env
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ LỖI: Chưa tìm thấy GEMINI_API_KEY trong file .env!")
    exit()

# 2. Khởi tạo Gemini Client
client = genai.Client(api_key=api_key)

def list_available_models():
    print("==================================================")
    print("🔍 ĐANG TRUY VẤN DANH SÁCH MODEL GEMINI KHẢ DỤNG...")
    print("==================================================")
    
    try:
        # Gọi API lấy danh sách tất cả các model
        models = client.models.list()
        
        count = 0
        for m in models:
            # Lọc ra các model hỗ trợ tạo nội dung (generateContent)
            if "generateContent" in m.supported_actions:
                count += 1
                # Lấy tên ngắn gọn của model (bỏ tiền tố 'models/')
                model_name = m.name.replace("models/", "")
                print(f"{count:02d}. 📌 Name: {model_name}")
                print(f"    ├─ Full Path : {m.name}")
                print(f"    └─ Display   : {m.display_name}")
                print("-" * 50)
                
        print(f"\n✅ Tổng cộng có {count} model Gemini khả dụng cho API Key của bạn.")
        
    except Exception as e:
        print(f"❌ Lỗi khi lấy danh sách model: {e}")

if __name__ == "__main__":
    list_available_models()