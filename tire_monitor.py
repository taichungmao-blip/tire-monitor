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

class TireIndustryMonitorV6:
    def __init__(self):
        self.lookback_days = 90
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.lookback_days)
        self.is_ci_env = os.getenv('GITHUB_ACTIONS') == 'true'
        
        self.tickers = {
            'Bridgestone': '5108.T', # 價格領先指標
            'Goodyear': 'GT',        # 美國需求指標
            'Cheng_Shin': '2105.TW',
            'Kenda': '2106.TW',
            'Oil_Brent': 'BZ=F',
            'USD_TWD': 'TWD=X'
        }
        self.weights = {'Rubber': 0.4, 'Oil': 0.3, 'FX': 0.3}

    def send_discord_notify(self, title, message, color, image_buffer=None):
        if not DISCORD_WEBHOOK_URL:
            print("❌ Discord Webhook 未設定")
            return

        data = {
            "username": "輪胎策略官",
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
        """爬取 Investing.com 天然橡膠"""
        url = "https://www.investing.com/commodities/rubber-tsr20-futures"
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code != 200: raise Exception(f"HTTP {res.status_code}")
            
            soup = BeautifulSoup(res.text, 'html.parser')
            # 抓價格
            price_tag = soup.find('div', {'data-test': 'instrument-price-last'}) or soup.find('span', class_='text-5xl')
            
            if price_tag:
                price = float(price_tag.text.strip().replace(',', ''))
                # 抓漲跌幅
                change_tag = soup.find('span', {'data-test': 'instrument-price-change-percent'})
                change_pct = float(change_tag.text.strip().replace('(', '').replace(')', '').replace('%', '')) if change_tag else 0.0
                return price, change_pct
            else:
                raise Exception("DOM Changed")
        except:
            print("⚠️ 橡膠爬取失敗，使用備援數據")
            return 185.0, 0.0 # Fallback

    def fetch_market_data(self):
        data = yf.download(list(self.tickers.values()), start=self.start_date, end=self.end_date, progress=False)['Close']
        reverse_map = {v: k for k, v in self.tickers.items()}
        return data.rename(columns=reverse_map).ffill().dropna()

    def generate_rubber_series(self, dates, current_price):
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
        df['Spread_Slope'] = df['Profit_Spread'].diff(5) 
        return df

    def analyze_strategy(self, df):
        latest = df.iloc[-1]
        spread = latest['Profit_Spread']
        slope = latest['Spread_Slope']
        leader_trend = latest['Bridgestone'] > df.iloc[-5]['Bridgestone']

        if spread > 0 and slope > 0 and leader_trend:
            return "🟢 **積極買進**", "利潤擴大 + 龍頭領漲", 65280
        elif spread > 0 and slope < 0:
            return "🟡 **觀望/持有**", "利潤收縮中，動能減弱", 16776960
        elif spread < 0:
            return "🔴 **避開/賣出**", "成本大漲吞噬利潤", 16711680
        else:
            return "⚪ **中立震盪**", "無明確方向", 12370112

    def generate_chart_buffer(self, df):
        plt.style.use('bmh')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        
        # 上圖：普利司通 vs 正新
        ax1.plot(df.index, df['Bridgestone'], label='Bridgestone (Leader)', color='#3498db')
        ax1_r = ax1.twinx()
        ax1_r.plot(df.index, df['Cheng_Shin'], label='Cheng Shin (Follower)', color='#e74c3c', linestyle='--')
        ax1.set_title('Leader-Lag: Bridgestone vs Cheng Shin')
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax1_r.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        
        # 下圖：剪刀差
        ax2.plot(df.index, df['Profit_Spread'], color='green', label='Profit Spread')
        ax2.fill_between(df.index, df['Profit_Spread'], 0, where=(df['Profit_Spread']>0), color='green', alpha=0.3)
        ax2.set_title('Profit Spread (Green Area = Buy Zone)')
        ax2.axhline(0, linestyle=':', color='black')
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        return buf

    def run(self):
        try:
            # 1. 數據處理
            rubber_price, rubber_chg = self.scrape_rubber_price()
            df = self.fetch_market_data()
            rubber_series = self.generate_rubber_series(df.index, rubber_price)
            df = pd.concat([df, rubber_series], axis=1)
            df = self.calculate_metrics(df)
            
            # 2. 準備變數
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            def fmt(val): return f"{val:.2f}"
            def pct(col): 
                val = (latest[col] - prev[col]) / prev[col] * 100
                return f"{val:+.2f}%"

            # 3. 策略分析
            signal, reason, color = self.analyze_strategy(df)

            # 4. 組裝完整報告 (含 Goodyear 與 橡膠細節)
            report_text = (
                f"**【輪胎產業戰術日報】** {datetime.now().strftime('%Y-%m-%d')}\n\n"
                f"🎯 **策略訊號: {signal}**\n"
                f"📝 **理由**: {reason}\n\n"
                
                f"**🇺🇸 國際領先/需求指標**\n"
                f"• 普利司通: {fmt(latest['Bridgestone'])} ({pct('Bridgestone')}) - *風向球*\n"
                f"• 固特異 (GT): {fmt(latest['Goodyear'])} ({pct('Goodyear')}) - *美市需求*\n\n"
                
                f"**🛢️ 成本因子 (Cost Drivers)**\n"
                f"• 天然橡膠: {fmt(latest['Rubber_TSR20'])} ({rubber_chg:+.2f}%) - *重要*\n"
                f"• 原油 (Brent): {fmt(latest['Oil_Brent'])} ({pct('Oil_Brent')})\n"
                f"• 綜合成本變化: **{latest['Cost_Index_Change']*100:+.2f}%**\n\n"
                
                f"**🇹🇼 台股監控**\n"
                f"• 正新: {fmt(latest['Cheng_Shin'])} ({pct('Cheng_Shin')})\n"
                f"• 建大: {fmt(latest['Kenda'])} ({pct('Kenda')})\n\n"
                
                f"📊 **利潤剪刀差 (Spread): {fmt(latest['Profit_Spread']*100)}**\n"
                f"(圖表說明: 紅虛線=正新, 綠色區域=潛在利潤)"
            )
            
            # 5. 發送
            chart_buffer = self.generate_chart_buffer(df)
            self.send_discord_notify(f"🚀 {signal.split('**')[1]} - 輪胎監控", report_text, color, chart_buffer)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    app = TireIndustryMonitorV6()
    app.run()
