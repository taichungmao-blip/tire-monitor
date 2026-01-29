import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import requests
import os
from datetime import datetime, timedelta

# ==========================================
# 1. 設定監控目標 (Configuration)
# ==========================================

# 國際領先指標 (The "Micron" of Tire Sector)
GLOBAL_LEADERS = {
    "5108.T": "普利司通 (日/龍頭)",
    "GT": "固特異 (美/需求)"
}

# 台灣輪胎股 (Followers)
TIRE_STOCKS = {
    "2105.TW": "正新 (2105)",
    "2106.TW": "建大 (2106)",
    "2109.TW": "華豐 (2109)"
}

# 原物料與匯率 (Cost Factors)
RAW_MATERIALS = {
    "CL=F": "原油 (油價)",
    "JR=F": "橡膠 (大阪期貨)", 
    "TWD=X": "美元兌台幣"
}

# 合併所有清單
ALL_TARGETS = {**GLOBAL_LEADERS, **TIRE_STOCKS, **RAW_MATERIALS}

LOOKBACK_DAYS = 180
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# ==========================================
# 2. 數據處理與分析
# ==========================================

def get_data():
    """下載數據"""
    print("下載全球輪胎股與原物料數據中...")
    tickers = list(ALL_TARGETS.keys())
    # 多抓一點時間以免均線計算不足
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS + 60)).strftime('%Y-%m-%d')
    
    data = yf.download(tickers, start=start_date, progress=False)['Close']
    data = data.ffill()
    return data

def analyze_market_status(df):
    """分析市場狀態"""
    # 取得最新報價與漲跌幅
    result = {}
    for code, name in ALL_TARGETS.items():
        if code in df.columns:
            price = df[code].iloc[-1]
            prev = df[code].iloc[-2]
            chg = (price - prev) / prev * 100
            result[code] = {"name": name, "price": price, "chg": chg}
    return result

def get_strategy_guide():
    """策略戰術板 (含國際龍頭解讀)"""
    return """
>>> **🍩 輪胎股戰術板 (Global Strategy)**
**1. 國際龍頭 (Leading Indicators):**
• 🇯🇵 **普利司通 (5108.T)**: 產業風向球。如果它創新高，代表全球輪胎業景氣復甦，正新/建大通常會落後補漲 (Lagging)。
• 🇺🇸 **固特異 (GT)**: 美國需求指標。若 GT 大跌，小心美國車市疲軟，台灣廠商出口會受創。

**2. 成本剪刀差 (Spread):**
• ✂️ **黃金買點**: 當 `油/橡膠(虛線)` 往下走，但 `普利司通/正新(實線)` 卻往上噴，代表利潤率將大幅擴張。

**3. 操作節奏:**
• 就像「看美光做南亞科」，當你看到普利司通發動攻勢時，通常台灣輪胎股還有 1-2 週的反應時間可以佈局。
"""

# ==========================================
# 3. 繪圖與通知
# ==========================================

def plot_comparison_chart(df):
    plt.figure(figsize=(12, 7))
    plt.style.use('bmh')
    
    # 正規化 (以第一天為 100，這樣才能把不同幣別放在同一個圖比較)
    norm = (df / df.iloc[0]) * 100
    
    # A. 畫國際龍頭 (粗線/顯眼)
    if '5108.T' in norm.columns:
        plt.plot(norm.index, norm['5108.T'], label='Bridgestone (Japan)', color='black', linewidth=2.5)
    if 'GT' in norm.columns:
        plt.plot(norm.index, norm['GT'], label='Goodyear (US)', color='blue', linewidth=2.0, alpha=0.8)

    # B. 畫台灣龍頭 (正新代表)
    if '2105.TW' in norm.columns:
        plt.plot(norm.index, norm['2105.TW'], label='Cheng Shin (TW)', color='red', linewidth=2.5)

    # C. 畫成本 (虛線/背景)
    if 'CL=F' in norm.columns:
        plt.plot(norm.index, norm['CL=F'], label='Crude Oil', linestyle=':', color='gray', alpha=0.6)

    plt.title(f"Tire Sector: Global Leaders vs Taiwan ({LOOKBACK_DAYS} Days)")
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    
    img_path = "global_tire_chart.png"
    plt.savefig(img_path, dpi=100, bbox_inches='tight')
    plt.close()
    return img_path

def send_discord(msg, img_path=None):
    if not DISCORD_WEBHOOK_URL:
        print(msg) # 本地測試用
        return
    
    data = {"content": msg}
    files = {}
    if img_path and os.path.exists(img_path):
        files = {"file": (os.path.basename(img_path), open(img_path, "rb"))}
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, data=data, files=files)
        print("✅ Discord 通知發送成功")
    finally:
        if files: files['file'][1].close()

def main():
    try:
        df = get_data()
        if df.empty: return
        
        market_stat = analyze_market_status(df)
        date_str = df.index[-1].strftime('%Y-%m-%d')
        
        # --- 組合訊息 ---
        msg = f"## 🌍 全球輪胎產業追蹤 `{date_str}`\n"
        
        # 1. 國際龍頭區
        msg += "### 👑 國際領先指標 (Leaders)\n"
        for code in GLOBAL_LEADERS:
            if code in market_stat:
                d = market_stat[code]
                icon = "🔥" if d['chg'] > 2 else ("❄️" if d['chg'] < -2 else "➖")
                msg += f"> **{d['name']}**: `{d['price']:.1f}` {icon} ({d['chg']:+.2f}%)\n"
        
        # 2. 台灣區
        msg += "\n### 🇹🇼 台灣輪胎股 (Followers)\n"
        for code in TIRE_STOCKS:
            if code in market_stat:
                d = market_stat[code]
                icon = "📈" if d['chg'] > 0 else "📉"
                msg += f"> **{d['name']}**: `{d['price']:.1f}` {icon} ({d['chg']:+.2f}%)\n"
        
        # 3. 成本區
        msg += "\n### 🛢️ 成本因子\n"
        if 'CL=F' in market_stat:
            oil = market_stat['CL=F']
            msg += f"> 原油: `{oil['chg']:+.2f}%`\n"
        if 'TWD=X' in market_stat:
            usd = market_stat['TWD=X']
            msg += f"> 美元/台幣: `{usd['price']:.2f}` ({(usd['chg']):+.2f}%)\n"

        # 4. 策略小抄
        msg += get_strategy_guide()

        # 5. 發送
        img_path = plot_comparison_chart(df)
        send_discord(msg, img_path)

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
