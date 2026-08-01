import os
from dotenv import load_dotenv
from google import genai

# 1. Nạp API Key từ file .env
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

def test_gemini_connection():
    print("==================================================")
    print("🧪 KIỂM TRA KẾT NỐI GEMINI API")
    print("==================================================")

    if not API_KEY:
        print("❌ LỖI: Không tìm thấy GEMINI_API_KEY trong file .env!")
        print("💡 Hãy kiểm tra lại file .env và đảm bảo đã thêm dòng: GEMINI_API_KEY=your_key")
        return

    print(f"🔑 Key tìm thấy: {API_KEY[:8]}...{API_KEY[-4:] if len(API_KEY) > 12 else ''}\n")

    # Khởi tạo Gemini Client
    client = genai.Client(api_key=API_KEY)

    # Danh sách các model phổ biến cần test
    test_models = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-3.5-flash']

    for model_name in test_models:
        print(f"🔄 Đang test kết nối tới model: [{model_name}]...")
        try:
            # Gửi một câu hỏi ngắn đơn giản
            response = client.models.generate_content(
                model=model_name,
                contents="Hãy trả lời ngắn gọn đúng 1 từ: 'OK'."
            )
            
            print(f"   ✅ KẾT NỐI THÀNH CÔNG!")
            print(f"   💬 Phản hồi từ Gemini: {response.text.strip()}\n")
            
        except Exception as e:
            print(f"   ❌ THẤT BẠI!")
            print(f"   🔍 Chi tiết lỗi: {e}\n")

    print("==================================================")

if __name__ == "__main__":
    test_gemini_connection()