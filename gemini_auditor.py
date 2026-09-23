import time
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import config

# Khởi tạo Gemini Client một lần duy nhất
_client = genai.Client(api_key=config.GEMINI_API_KEY)


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


def audit_signal_with_gemini(symbol: str, entry_price: float, rsi: float, adx: float, vol_ratio: float,
                             candles_summary: str, stop_loss: float = None, take_profit: float = None,
                             atr: float = None, strategy_type: str = "SNIPER_TREND") -> GeminiAuditResult:
    """
    Gửi bối cảnh giao dịch sang Gemini Flash để thẩm định lại rủi ro cho cả 2 chế độ (Trend & Sideway).
    Tối ưu hóa giải phóng bộ nhớ (Memory-efficient).
    """
    sl_pct_desc = f"-{(entry_price - stop_loss)/entry_price*100:.1f}%" if stop_loss else "N/A"
    tp_pct_desc = f"+{(take_profit - entry_price)/entry_price*100:.1f}%" if take_profit else "N/A"

    sl_info = f"    • Dự kiến Cắt lỗ (SL): ${stop_loss:.2f} ({sl_pct_desc})\n" if stop_loss else ""
    tp_info = f"    • Dự kiến Chốt lời (TP): ${take_profit:.2f} ({tp_pct_desc})\n" if take_profit else ""
    atr_info = f"    • Biến động ATR(14): ${atr:.2f} ({atr/entry_price*100:.1f}% giá)\n" if atr and atr > 0 else ""

    if strategy_type == "SIDEWAY_RANGE":
        strat_header = "CHẾ ĐỘ: BẮT ĐÁY BIÊN HỘP SIDEWAY (MEAN REVERSION AT LOWER BOLLINGER BAND)"
        crit_desc = """
    === TIÊU CHÍ THẨM ĐỊNH SIDEWAY RANGE (BẮT ĐÁY BIÊN DƯỚI) ===
    1. KIỂM TRA LỰC HẤP THỤ ĐÁY: Ưu tiên nến rút chân dưới (Bullish Wick / Pinbar / Hammer) chạm dải dưới Lower BB và có volume hấp thụ đỡ giá.
    2. TRÁNH DAO RƠI (FALLING KNIFE): Nếu 3-4 nến gần nhất là nến đỏ thân dài liên tục phá thủng mọi hỗ trợ mà không có lực mua đỡ -> Chọn ngay 'REJECT' (Điểm < 7).
    3. ĐIỀU KIỆN 'APPROVE': Chỉ phê duyệt 'APPROVE' (Điểm >= 8) khi giá đã chững lại đà giảm, RSI quá bán sâu (<= 38), kỳ vọng nhịp hồi phục kỹ thuật về trục giữa SMA20 / Upper BB an toàn.
        """
    else:
        strat_header = "CHẾ ĐỘ: BẮN TỈA THEO XU HƯỚNG (SNIPER TREND FOLLOWING 4H + 1H PULLBACK)"
        crit_desc = """
    === TIÊU CHÍ THẨM ĐỊNH SNIPER TREND FOLLOWING (KHẮT KHE) ===
    1. KIỂM TRA RÂU NẾN & BẪY GIÁ: Nếu 1-2 nến gần nhất có râu trên dài từ chối giá (Selling Wick) hoặc mô hình Shooting Star / Bearish Engulfing -> Chọn ngay 'REJECT' (Điểm < 7).
    2. KIỂM TRA ĐÀ TĂNG: Nếu giá đã tăng dốc đứng liên tục 4-5 nến xanh mà không có nhịp nghỉ (Overextended / Đu đỉnh) -> Chọn ngay 'REJECT' (Điểm < 7).
    3. ĐIỀU KIỆN 'APPROVE': Chỉ phê duyệt 'APPROVE' (Điểm >= 8) khi cấu trúc nến tăng khỏe, tích lũy nén chặt, có lực đẩy dòng tiền rõ ràng.
        """

    prompt = f"""
    Bạn là một Chuyên gia Quản trị Rủi ro Quỹ Định Lượng (Quant Portfolio Risk Manager).
    Hệ thống vừa phát hiện một điểm vào lệnh MUA (BUY SIGNAL) cho cặp `{symbol}`.
    {strat_header}
    Mục tiêu tối thượng: THÀ BỎ LỠ CƠ HỘI CHỨ TUYỆT ĐỐI KHÔNG VÀO LỆNH XẤU / RỦI RO CAO.

    === THÔNG SỐ KỸ THUẬT VỪA KÍCH HOẠT ===
    • Cặp giao dịch: {symbol}
    • Giá vào lệnh (Entry): ${entry_price:.2f}
{sl_info}{tp_info}{atr_info}    • Chỉ số RSI (1H): {rsi:.1f}
    • Chỉ số ADX (1H - Độ mạnh xu hướng): {adx:.1f}
    • Khối lượng nến tín hiệu: Gấp {vol_ratio:.2f} lần trung bình 20 phiên.

    === DIỄN BIẾN 5 CÂY NẾN 1H GẦN NHẤT (Mở - Đỉnh - Đáy - Đóng) ===
    {candles_summary}

    {crit_desc}
    """

    models_to_try = [
        getattr(config, 'GEMINI_PRIMARY_MODEL', 'gemini-3.6-flash'),
        getattr(config, 'GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')
    ]

    last_error_str = ""
    for model_name in models_to_try:
        try:
            response = _client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GeminiAuditResult,
                    temperature=0.2,
                ),
            )
            raw_text = str(response.text)
            del response  # Giải phóng response payload lập tức
            return GeminiAuditResult.model_validate_json(raw_text)
        except Exception as e:
            # Ngắt tham chiếu traceback để tránh giữ frame bộ nhớ trong closure
            last_error_str = str(e)
            e = None
            print(f"⚠️ [Auditor] Model {model_name} gặp sự cố cho {symbol}: {last_error_str}. Đang chuyển model...")
            time.sleep(1)

    print(f"❌ [Auditor] Không thể gọi bất kỳ Gemini model nào để thẩm định {symbol}: {last_error_str}")
    return None