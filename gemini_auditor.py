from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import config

# Khởi tạo Gemini Client
client = genai.Client(api_key=config.GEMINI_API_KEY)


# --- ĐỊNH NGHĨA ĐỊNH DẠNG JSON TRẢ VỀ TỪ GEMINI ---
class GeminiAuditResult(BaseModel):
    decision: str = Field(
        description="Quyết định cuối cùng: 'APPROVE' (Đồng ý) hoặc 'REJECT' (Từ chối do rủi ro)"
    )
    confidence_score: int = Field(
        description="Điểm độ tin cậy từ 1 đến 10 dựa trên cấu trúc nến và bối cảnh"
    )
    risk_assessment: str = Field(
        description="Tóm tắt 1 câu về rủi ro nhận thấy (VD: Nến rút chân trên dài, chạm vùng kháng cự...)"
    )
    ai_reasoning: str = Field(
        description="Lý do chi tiết 2-3 câu giải thích tại sao chấp nhận hoặc từ chối"
    )


def audit_signal_with_gemini(symbol: str, entry_price: float, rsi: float, adx: float, vol_ratio: float, candles_summary: str) -> GeminiAuditResult:
    """
    Gửi bối cảnh giao dịch sang Gemini 2.5 Flash để thẩm định lại rủi ro.
    """
    prompt = f"""
    Bạn là một Chuyên gia Quản trị Rủi ro (Quant Risk Manager) trong thị trường Crypto.
    Hệ thống thuật toán Python vừa phát hiện một điểm vào lệnh MUA (BUY SIGNAL) cho cặp `{symbol}`.
    Nhiệm vụ của bạn là kiểm tra lại BỐI CẢNH 5 nến gần nhất và thẩm định xem có bẫy tăng giá (Fakeout) hay không.

    === THÔNG SỐ KỸ THUẬT VỪA KÍCH HOẠT ===
    • Cặp giao dịch: {symbol}
    • Giá vào lệnh (Entry): ${entry_price:.2f}
    • Chỉ số RSI (1H): {rsi:.1f}
    • Chỉ số ADX (1H - Độ mạnh xu hướng): {adx:.1f}
    • Khối lượng nến tín hiệu: Gấp {vol_ratio:.2f} lần trung bình 20 phiên.
    • Lọc xu hướng 4H: UPTREND (Giá đang nằm trên đường EMA 200).

    === DIỄN BIẾN 5 CÂY NẾN 1H GẦN NHẤT (Mở - Đỉnh - Đáy - Đóng) ===
    {candles_summary}

    === QUY TRÌNH THẨM ĐỊNH ===
    1. Kiểm tra 5 nến gần nhất xem có nến nào bị bán tháo rút chân trên rất dài (Râu nến trên lớn gấp đôi thân) hay không.
    2. Đánh giá đà tăng có bị kiệt sức (Exhaustion) không.
    3. Trả về 'APPROVE' nếu điểm tin cậy >= 7, ngược lại chọn 'REJECT'.
    """

    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiAuditResult,
                temperature=0.2, # Giữ nhiệt độ thấp để đánh giá khách quan
            ),
        )
        # Ép kiểu dữ liệu trả về thành Pydantic Object
        return GeminiAuditResult.model_validate_json(response.text)
    except Exception as e:
        print(f"❌ Lỗi khi gọi Gemini API thẩm định {symbol}: {e}")
        return None
    