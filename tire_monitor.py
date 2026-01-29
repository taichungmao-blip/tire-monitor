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
# 設定區 (Configuration)
# ==========================================
# 從環境變數讀取 GitHub Secrets
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

class TireIndustryMonitorV4:
    def __init__(self):
        self.lookback_days = 90
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.lookback_days)
        
        # 判斷是否在 CI 環境 (GitHub Actions 通常會有 GITHUB_ACTIONS=true)
        self.is_ci_env = os.getenv('GITHUB_ACTIONS') == 'true'
        
        self.tickers = {
            'Bridgestone': '5108.T',
            'Goodyear': 'GT',
            'Cheng_Shin': '2105.TW',
            'Kenda': '2106.TW',
            'Oil_Brent': 'BZ=F',
            'USD_TWD': 'TWD=X'
        }
        self.weights = {'Rubber': 0.4, 'Oil': 0.3, 'FX': 0.3}

    def send_discord_notify(self, title, message, image_buffer=None, color=65280):
        """發送 Discord Webhook 通知 (支援附圖)"""
        if not DISCORD_WEBHOOK_URL:
            print("❌ 錯誤: 環境變數 'DISCORD_WEBHOOK_URL' 未設定，無法發送通知。")
            return

        # 1. 先發送文字訊息 (Embed)
        data = {
            "username": "輪胎產業監控機器人",
            "embeds": [{
                "title": title,
                "description": message,
                "color": color,
                "footer": {"text": f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
            }]
        }
        
        try:
            # 發送文字
            requests.post(DISCORD_WEBHOOK_URL, json=data)
            
            # 2. 如果有圖表，發送圖表檔案
            if image_buffer:
                image_buffer.seek(0)
                files = {
                    'file': ('chart.png', image_buffer, 'image/png')
                }
                # Discord Webhook 發送檔案不需要 Embed 格式，直接 multipart/form-data
                requests.post(DISCORD_WEBHOOK_URL, files=files)
                print("✅ Discord 通知與圖表已發送")
            else:
                print("✅ Discord 通知已發送 (無圖表)")
                
        except Exception as e:
            print(f"❌ Discord 連線錯誤: {e}")

    def scrape_rubber_price(self):
        """爬取 Investing.com"""
        url = "https://www.investing.com/commodities/rubber-tsr20-futures"
        print(f"🕸️ 正在爬取: {url}")
        
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                raise Exception(f"HTTP {res.status_code}")
            
            soup = BeautifulSoup(res.text, 'html.parser')
            # 嘗試抓取價格 (針對 Investing.com 動態改版做的容錯)
            price_tag = soup.find('div', {'data-test': 'instrument-price-last'}) or soup.find('span', class_='text-5xl')
            
            if price_tag:
                price = float(price_tag.text.strip().replace(',', ''))
                
                # 抓漲跌幅
                change_tag = soup.find('span', {'data-test': 'instrument-price-change-percent'})
                change_pct = float(change_tag.text.strip().replace('(', '').replace(')', '').replace('%', '')) if change_tag else 0.0
                
                return price, change_pct
            else:
                raise Exception("DOM 解析失敗")

        except Exception as e:
            print(f"⚠️ 爬蟲失敗 ({e}) -> 使用預設值")
            return 185.0, 0.0 # Fallback

    def fetch_market_data(self):
        print(f"📥 下載 Yahoo Finance 數據...")
        data = yf.download(list(self.tickers.values()), start=self.start_date, end=self.end_date, progress=False)['Close']
        reverse_map = {v: k for k, v in self.tickers.items()}
        data = data.rename(columns=reverse_map)
        return data.ffill().dropna()

    def generate_rubber_series(self, dates, current_price):
        """生成橡膠歷史模擬序列 (用於填補圖表)"""
        np.random.seed(42)
        prices = [current_price]
        for _ in range(len(dates)-1):
            prices.append(prices[-1] - np.random.normal(0, 1.5))
        prices.reverse()
        return pd.Series(prices, index=dates, name='Rubber_TSR20')

    def calculate_metrics(self, df):
        df_pct = df.pct_change().fillna(0)
        
        # 綜合成本指數
        df['Cost_Index_Change'] = (
            df_pct['Rubber_TSR20'] * self.weights['Rubber'] +
            df_pct['Oil_Brent'] * self.weights['Oil'] +
            df_pct['USD_TWD'] * self.weights['FX']
        )
        df['Composite_Cost_Cum'] = df['Cost_Index_Change'].cumsum()
        
        # 利潤剪刀差
        df['Bridgestone_Cum'] = df_pct['Bridgestone'].cumsum()
        df['Profit_Spread'] = df['Bridgestone_Cum'] - df['Composite_Cost_Cum']
        return df

    def generate_chart_buffer(self, df):
        """繪圖並回傳 Buffer 物件 (不存檔，直接在記憶體傳輸)"""
        plt.style.use('bmh')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        
        # Chart 1
        ax1.plot(df.index, df['Bridgestone'], label='Bridgestone (JP)', color='#3498db')
        ax1_r = ax1.twinx()
        ax1_r.plot(df.index, df['Cheng_Shin'], label='Cheng Shin (TW)', color='#e74c3c', linestyle='--')
        ax1.set_title('Leader (Bridgestone) vs Follower (Cheng Shin)')
        ax1.legend(loc='upper left')
        
        # Chart 2
        ax2.plot(df.index, df['Profit_Spread'], color='green', label='Profit Spread')
        ax2.fill_between(df.index, df['Profit_Spread'], 0, where=(df['Profit_Spread']>0), color='green', alpha=0.3)
        ax2.fill_between(df.index, df['Profit_Spread'], 0, where=(df['Profit_Spread']<0), color='red', alpha=0.3)
        ax2.set_title('Profit Spread (Margin Expansion Indicator)')
        ax2.axhline(0, linestyle=':', color='black')
        
        plt.tight_layout()
        
        # 將圖片存入 BytesIO
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close() # 釋放記憶體
        return buf

    def run(self):
        try:
            # 1. 獲取數據
            rubber_price, rubber_chg = self.scrape_rubber_price()
            df = self.fetch_market_data()
            
            # 2. 處理數據
            rubber_series = self.generate_rubber_series(df.index, rubber_price)
            df = pd.concat([df, rubber_series], axis=1)
            df = self.calculate_metrics(df)
            
            # 3. 準備報告
            latest = df.iloc[-1]
            fmt = lambda v: f"{v:.2f}"
            
            report_text = (
                f"**【全球輪胎產業追蹤】** {datetime.now().strftime('%Y-%m-%d')}\n\n"
                f"**🏭 領先指標**\n"
                f"• 普利司通: {fmt(latest['Bridgestone'])}\n"
                f"• 固特異: {fmt(latest['Goodyear'])}\n\n"
                f"**🛢️ 成本因子**\n"
                f"• 天然橡膠: {fmt(latest['Rubber_TSR20'])} ({rubber_chg:+.2f}%)\n"
                f"• 綜合成本指數: {latest['Cost_Index_Change']*100:+.2f}%\n\n"
                f"**🇹🇼 台廠**\n"
                f"• 正新: {fmt(latest['Cheng_Shin'])}\n"
                f"• 建大: {fmt(latest['Kenda'])}\n\n"
                f"⚡ **Spread**: {fmt(latest['Profit_Spread']*100)}"
            )
            
            # 4. 繪圖 (生成 Buffer)
            chart_buffer = self.generate_chart_buffer(df)
            
            # 5. 發送通知
            self.send_discord_notify("🚀 輪胎產業日報", report_text, chart_buffer)
            
            # 本地開發時，如果想看圖
            if not self.is_ci_env:
                print("非 CI 環境，腳本執行完畢。")
                
        except Exception as e:
            print(f"❌ 執行過程發生錯誤: {e}")
            sys.exit(1)

if __name__ == "__main__":
    app = TireIndustryMonitorV4()
    app.run()
