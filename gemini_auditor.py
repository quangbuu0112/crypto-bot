import time
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


def audit_signal_with_gemini(symbol: str, entry_price: float, rsi: float, adx: float, vol_ratio: float, candles_summary: str, stop_loss: float = None, take_profit: float = None, atr: float = None) -> GeminiAuditResult:
    """
    Gửi bối cảnh giao dịch sang Gemini 3.5 Flash để thẩm định lại rủi ro.
    """
    tp1_mult = getattr(config, 'ATR_TP1_MULTIPLIER', 1.2)
    tp2_mult = getattr(config, 'ATR_TP2_MULTIPLIER', 3.0)
    sl_mult = getattr(config, 'ATR_SL_MULTIPLIER', 1.4)

    sl_info = f"    • Dự kiến Cắt lỗ (SL ban đầu): ${stop_loss:.2f} (-{(entry_price - stop_loss)/entry_price*100:.1f}% | {sl_mult}x ATR)\n" if stop_loss else ""
    tp_info = f"    • Dự kiến Chốt lời (TP1/TP2): ${take_profit:.2f} (+{(take_profit - entry_price)/entry_price*100:.1f}% | TP1:{tp1_mult}x, TP2:{tp2_mult}x ATR)\n" if take_profit else ""
    atr_info = f"    • Biến động ATR(14): ${atr:.2f} ({atr/entry_price*100:.1f}% giá)\n" if atr and atr > 0 else ""

    prompt = f"""
    Bạn là một Chuyên gia Quản trị Rủi ro Quỹ Định Lượng (Quant Portfolio Risk Manager) theo phong cách SNIPER QUALITY (Bắn tỉa chất lượng cao).
    Hệ thống vừa phát hiện một điểm vào lệnh MUA (BUY SIGNAL) cho cặp `{symbol}`.
    Mục tiêu tối thượng: THÀ BỎ LỠ CƠ HỘI CHỨ TUYỆT ĐỐI KHÔNG VÀO LỆNH XẤU / RỦI RO CAO.

    === THÔNG SỐ KỸ THUẬT VỪA KÍCH HOẠT ===
    • Cặp giao dịch: {symbol}
    • Giá vào lệnh (Entry): ${entry_price:.2f}
{sl_info}{tp_info}{atr_info}    • Chỉ số RSI (1H): {rsi:.1f} (Vùng tối ưu: 42 - 65)
    • Chỉ số ADX (1H - Độ mạnh xu hướng): {adx:.1f}
    • Khối lượng nến tín hiệu: Gấp {vol_ratio:.2f} lần trung bình 20 phiên.
    • Lọc xu hướng 4H: UPTREND MẠNH (Trend Alignment: Giá > EMA 50 > EMA 200).

    === DIỄN BIẾN 5 CÂY NẾN 1H GẦN NHẤT (Mở - Đỉnh - Đáy - Đóng) ===
    {candles_summary}

    === TIÊU CHÍ THẨM ĐỊNH SNIPER QUALITY (KHẮT KHE) ===
    1. KIỂM TRA RÂU NẾN & BẪY GIÁ: Nếu 1-2 nến gần nhất có râu trên dài từ chối giá (Selling Wick) hoặc mô hình nến Shooting Star / Bearish Engulfing -> Chọn ngay 'REJECT' (Điểm < 7).
    2. KIỂM TRA ĐÀ TĂNG: Nếu giá đã tăng dốc đứng liên tục 4-5 nến xanh mà không có nhịp nghỉ (Overextended / Đu đỉnh) -> Chọn ngay 'REJECT' (Điểm < 7).
    3. ĐIỀU KIỆN 'APPROVE': Chỉ phê duyệt 'APPROVE' khi cấu trúc nến tăng khỏe, tích lũy nén chặt, có lực đẩy dòng tiền rõ ràng và điểm tin cậy đạt từ 8 ĐẾN 10 ĐIỂM (>= 8/10).
    """

    models_to_try = [
        getattr(config, 'GEMINI_PRIMARY_MODEL', 'gemini-3.6-flash'),
        getattr(config, 'GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')
    ]

    last_error = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
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
            last_error = e
            print(f"[CANH BAO] [Auditor] Model {model_name} gap su co cho {symbol}: {e}. Dang chuyen sang model tiep theo...")
            time.sleep(1)

    print(f"[LOI] Khong the goi bat ky Gemini model nao de tham dinh {symbol}: {last_error}")
    return None
    