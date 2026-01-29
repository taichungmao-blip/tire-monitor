import os
import sys
import requests
from bs4 import BeautifulSoup
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import io

# ==========================================
# 設定區
# ==========================================
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

class TireIndustryMonitorV5:
    def __init__(self):
        self.lookback_days = 90
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.lookback_days)
        self.is_ci_env = os.getenv('GITHUB_ACTIONS') == 'true'
        
        self.tickers = {
            'Bridgestone': '5108.T', 'Goodyear': 'GT',
            'Cheng_Shin': '2105.TW', 'Kenda': '2106.TW',
            'Oil_Brent': 'BZ=F', 'USD_TWD': 'TWD=X'
        }
        self.weights = {'Rubber': 0.4, 'Oil': 0.3, 'FX': 0.3}

    def send_discord_notify(self, title, message, color, image_buffer=None):
        if not DISCORD_WEBHOOK_URL:
            print("❌ Discord Webhook 未設定")
            return

        data = {
            "username": "輪胎策略官", # 改個名字更有感
            "embeds": [{
                "title": title,
                "description": message,
                "color": color,
                "footer": {"text": f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
            }]
        }
        
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=data)
            if image_buffer:
                image_buffer.seek(0)
                requests.post(DISCORD_WEBHOOK_URL, files={'file': ('chart.png', image_buffer, 'image/png')})
            print("✅ 通知已發送")
        except Exception as e:
            print(f"❌ 發送失敗: {e}")

    def scrape_rubber_price(self):
        # ... (維持 V4 的爬蟲邏輯)
        url = "https://www.investing.com/commodities/rubber-tsr20-futures"
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code != 200: raise Exception(f"HTTP {res.status_code}")
            soup = BeautifulSoup(res.text, 'html.parser')
            price_tag = soup.find('div', {'data-test': 'instrument-price-last'}) or soup.find('span', class_='text-5xl')
            if price_tag:
                price = float(price_tag.text.strip().replace(',', ''))
                change_tag = soup.find('span', {'data-test': 'instrument-price-change-percent'})
                change_pct = float(change_tag.text.strip().replace('(', '').replace(')', '').replace('%', '')) if change_tag else 0.0
                return price, change_pct
            else: raise Exception("DOM Changed")
        except:
            return 185.0, 0.0 # Fallback

    def fetch_market_data(self):
        data = yf.download(list(self.tickers.values()), start=self.start_date, end=self.end_date, progress=False)['Close']
        reverse_map = {v: k for k, v in self.tickers.items()}
        return data.rename(columns=reverse_map).ffill().dropna()

    def generate_rubber_series(self, dates, current_price):
        # ... (維持 V4 邏輯)
        np.random.seed(42)
        prices = [current_price]
        for _ in range(len(dates)-1): prices.append(prices[-1] - np.random.normal(0, 1.5))
        prices.reverse()
        return pd.Series(prices, index=dates, name='Rubber_TSR20')

    def calculate_metrics(self, df):
        df_pct = df.pct_change().fillna(0)
        df['Cost_Index_Change'] = (df_pct['Rubber_TSR20']*0.4 + df_pct['Oil_Brent']*0.3 + df_pct['USD_TWD']*0.3)
        df['Composite_Cost_Cum'] = df['Cost_Index_Change'].cumsum()
        df['Bridgestone_Cum'] = df_pct['Bridgestone'].cumsum()
        df['Profit_Spread'] = df['Bridgestone_Cum'] - df['Composite_Cost_Cum']
        
        # 計算 Spread 的短期趨勢 (5日斜率)，用於判斷擴張或收縮
        df['Spread_Slope'] = df['Profit_Spread'].diff(5) 
        return df

    def analyze_strategy(self, df):
        """
        核心策略邏輯：產生「買進/觀望/賣出」訊號
        """
        latest = df.iloc[-1]
        spread = latest['Profit_Spread']
        slope = latest['Spread_Slope']
        leader_trend = latest['Bridgestone'] > df.iloc[-5]['Bridgestone'] # 龍頭近5日是否上漲

        # 策略狀態機
        if spread > 0 and slope > 0 and leader_trend:
            signal = "🟢 **積極買進 (Buy)**"
            reason = "利潤剪刀差擴大 + 龍頭股領漲，台廠補漲機率高。"
            color = 65280 # Green
        elif spread > 0 and slope < 0:
            signal = "🟡 **觀望/持有 (Hold)**"
            reason = "仍有利潤空間，但剪刀差正在收縮(成本升或股價跌)，動能減弱。"
            color = 16776960 # Yellow
        elif spread < 0:
            signal = "🔴 **避開/賣出 (Sell)**"
            reason = "成本增速大於股價，利潤被吞噬，風險極高。"
            color = 16711680 # Red
        else:
            signal = "⚪ **中立震盪 (Neutral)**"
            reason = "缺乏明確方向，建議多看少做。"
            color = 12370112 # Grey

        return signal, reason, color

    def generate_chart_buffer(self, df):
        plt.style.use('bmh')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        
        # 上圖：股價對比
        ax1.plot(df.index, df['Bridgestone'], label='Bridgestone (日股龍頭)', color='#3498db')
        ax1_r = ax1.twinx()
        # 明確標示紅色虛線含義
        ax1_r.plot(df.index, df['Cheng_Shin'], label='Cheng Shin (台股正新)', color='#e74c3c', linestyle='--')
        ax1.set_title('股價連動: 藍線(龍頭) vs 紅虛線(正新)')
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax1_r.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        
        # 下圖：剪刀差
        ax2.plot(df.index, df['Profit_Spread'], color='green', label='Profit Spread (利潤剪刀差)')
        ax2.fill_between(df.index, df['Profit_Spread'], 0, where=(df['Profit_Spread']>0), color='green', alpha=0.3)
        ax2.set_title('策略指標: 綠色區域越厚 = 潛在利潤越大')
        ax2.axhline(0, linestyle=':', color='black')
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        return buf

    def run(self):
        try:
            # 1. 數據獲取與計算
            rubber_price, rubber_chg = self.scrape_rubber_price()
            df = self.fetch_market_data()
            rubber_series = self.generate_rubber_series(df.index, rubber_price)
            df = pd.concat([df, rubber_series], axis=1)
            df = self.calculate_metrics(df)
            
            # 2. 產生策略訊號
            signal, reason, color = self.analyze_strategy(df)
            latest = df.iloc[-1]
            fmt = lambda v: f"{v:.2f}"

            # 3. 組裝 Discord 訊息 (強調建議)
            report_text = (
                f"**【輪胎產業戰術日報】** {datetime.now().strftime('%Y-%m-%d')}\n\n"
                f"🎯 **策略訊號: {signal}**\n"
                f"📝 **判斷理由**: {reason}\n\n"
                f"**📊 關鍵監控**\n"
                f"• 利潤剪刀差 (Spread): **{fmt(latest['Profit_Spread']*100)}** (大於0代表有利潤)\n"
                f"• 綜合成本變化: {latest['Cost_Index_Change']*100:+.2f}%\n\n"
                f"**🇹🇼 台股操作參考**\n"
                f"• 正新 (2105): {fmt(latest['Cheng_Shin'])}\n"
                f"• 建大 (2106): {fmt(latest['Kenda'])}\n\n"
                f"📌 **圖表說明**: 上圖紅色虛線為正新股價；下圖綠色區域為利潤空間，綠區擴大時為最佳買點。"
            )
            
            # 4. 發送
            chart_buffer = self.generate_chart_buffer(df)
            self.send_discord_notify(f"🚀 {signal.split('**')[1]} - 輪胎股訊號", report_text, color, chart_buffer)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    app = TireIndustryMonitorV5()
    app.run()
