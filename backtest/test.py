import os
import time
import ccxt
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 1. Load API Key
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)
exchange = ccxt.binance({'enableRateLimit': True})

# --- PYDANTIC SCHEMA CHO GEMINI ---
class GeminiAuditResult(BaseModel):
    decision: str = Field(description="Quyết định: 'APPROVE' hoặc 'REJECT'")
    confidence_score: int = Field(description="Điểm độ tin cậy từ 1-10")
    risk_assessment: str = Field(description="Đánh giá rủi ro ngắn gọn")
    ai_reasoning: str = Field(description="Lý do chi tiết")


def audit_with_gemini(symbol, entry_price, rsi, adx, vol_ratio, candles_summary) -> GeminiAuditResult:
    """Gửi dữ liệu quá khứ cho Gemini đánh giá"""
    prompt = f"""
    Bạn là Chuyên gia Quản trị Rủi ro Crypto.
    Hệ thống vừa phát hiện tín hiệu MUA lịch sử cho cặp `{symbol}` tại giá ${entry_price:.2f}.

    === CHỈ BÁO KỸ THUẬT TẠI THỜI ĐIỂM ĐÓ ===
    • RSI (1H): {rsi:.1f} | ADX (1H): {adx:.1f}
    • Volume: Gấp {vol_ratio:.2f} lần trung bình 20 phiên.
    • Trend 4H: UPTREND (Giá > EMA200).

    === DIỄN BIẾN 5 CÂY NẾN 1H NGAY TRƯỚC ĐÓ ===
    {candles_summary}

    Hãy soi cấu trúc nến xem có dấu hiệu xả hàng / râu nến trên dài / cản cứng không.
    Nếu điểm tin cậy >= 7 chọn 'APPROVE', ngược lại chọn 'REJECT'.
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiAuditResult,
                temperature=0.1,
            ),
        )
        return GeminiAuditResult.model_validate_json(response.text)
    except Exception as e:
        print(f"❌ Lỗi Gemini API: {e}")
        return None


def run_backtest_with_ai(symbol="BTC/USDT", limit=300):
    print(f"🔄 Đang cào {limit} nến lịch sử của {symbol} để Backtest kết hợp Gemini AI...\n")

    # Lấy dữ liệu 4H và 1H
    ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe="4h", limit=limit)
    ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe="1h", limit=limit)

    df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    df_4h['timestamp'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='ms')

    # Tính chỉ báo
    df_4h['EMA_200_4h'] = ta.ema(df_4h['close'], length=200)
    df_4h_sub = df_4h[['timestamp', 'EMA_200_4h']].sort_values('timestamp')

    df_1h['EMA_20_1h'] = ta.ema(df_1h['close'], length=20)
    df_1h['RSI_1h'] = ta.rsi(df_1h['close'], length=14)
    adx_df = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
    df_1h['ADX_14_1h'] = adx_df['ADX_14']
    df_1h['VOL_MA20_1h'] = df_1h['volume'].rolling(20).mean()

    # Ghép khung 4H vào 1H
    df = pd.merge_asof(df_1h.sort_values('timestamp'), df_4h_sub, on='timestamp', direction='backward')

    # Thống kê
    tech_signals = 0          # Tổng tín hiệu Kỹ thuật Python báo
    tech_correct = 0          # Tín hiệu Kỹ thuật đoán đúng

    ai_approved_signals = 0   # Tín hiệu được Gemini ĐỒNG Ý
    ai_approved_correct = 0   # Tín hiệu Gemini ĐỒNG Ý và ĐÚNG THỰC TẾ

    ai_rejected_signals = 0   # Tín hiệu Gemini TỪ CHỐI
    ai_rejected_was_wrong = 0 # Tín hiệu Gemini TỪ CHỐI mà THỰC TẾ LỖ THẬT (AI lọc đúng bẫy)

    # Duyệt quá khứ
    for i in range(200, len(df) - 1):
        past = df.iloc[i]
        future = df.iloc[i + 1]

        cond_4h = past['close'] > past['EMA_200_4h']
        cond_ema = past['close'] > past['EMA_20_1h']
        cond_rsi = 50 < past['RSI_1h'] < 68
        cond_adx = past['ADX_14_1h'] > 20
        cond_vol = past['volume'] > (1.1 * past['VOL_MA20_1h'])

        if cond_4h and cond_ema and cond_rsi and cond_adx and cond_vol:
            tech_signals += 1
            is_actually_win = future['close'] > past['close']
            if is_actually_win:
                tech_correct += 1

            # Tóm tắt 5 nến trước đó cho Gemini
            last_5 = df.iloc[i-5:i]
            candles_summary = ""
            for _, row in last_5.iterrows():
                candles_summary += f"- Nến {row['timestamp'].strftime('%H:%M')}: O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}\n"

            vol_ratio = past['volume'] / past['VOL_MA20_1h']

            print(f"🔍 [{past['timestamp'].strftime('%Y-%m-%d %H:%M')}] Tín hiệu #{tech_signals} -> Đang gửi Gemini thẩm định...")
            
            ai_res = audit_with_gemini(symbol, past['close'], past['RSI_1h'], past['ADX_14_1h'], vol_ratio, candles_summary)
            
            time.sleep(1) # Tránh Rate Limit Gemini Free

            if ai_res:
                if ai_res.decision == "APPROVE":
                    ai_approved_signals += 1
                    status = "✅ THẮNG" if is_actually_win else "❌ THUA"
                    if is_actually_win:
                        ai_approved_correct += 1
                    print(f"   └─🤖 Gemini: APPROVE ({ai_res.confidence_score}/10) | Thực tế: {status}")
                else:
                    ai_rejected_signals += 1
                    status = "❌ THUA (AI né đúng bẫy!)" if not is_actually_win else "✅ THẮNG (AI bỏ hụt)"
                    if not is_actually_win:
                        ai_rejected_was_wrong += 1
                    print(f"   └─⛔ Gemini: REJECT ({ai_res.confidence_score}/10)  | Thực tế: {status}")

    # --- KẾT QUẢ SO SÁNH ---
    tech_winrate = (tech_correct / tech_signals * 100) if tech_signals > 0 else 0
    ai_winrate = (ai_approved_correct / ai_approved_signals * 100) if ai_approved_signals > 0 else 0

    print("\n=================== BÁO CÁO ĐO ĐỘ CHÍNH XÁC KHI CÓ AI ===================")
    print(f"• Cặp giao dịch                   : {symbol}")
    print(f"• Tổng số tín hiệu Kỹ thuật báo    : {tech_signals} lệnh")
    print(f"• Win Rate CHỈ DÙNG KỸ THUẬT       : {tech_winrate:.2f}% ({tech_correct}/{tech_signals})")
    print("-------------------------------------------------------------------------")
    print(f"• Số lệnh Gemini ĐỒNG Ý (APPROVE)  : {ai_approved_signals} lệnh")
    print(f"• Win Rate KHI CÓ GEMINI AI AUDIT  : {ai_winrate:.2f}% ({ai_approved_correct}/{ai_approved_signals})")
    print("-------------------------------------------------------------------------")
    print(f"• Số bẫy xả Gemini TỪ CHỐI (REJECT): {ai_rejected_signals} lệnh")
    print(f"• Tỷ lệ AI lọc ĐÚNG BẪY THẤT BẠI    : {(ai_rejected_was_wrong/ai_rejected_signals*100) if ai_rejected_signals>0 else 0:.2f}%")
    print("=========================================================================\n")

if __name__ == "__main__":
    run_backtest_with_ai("BTC/USDT", limit=300)