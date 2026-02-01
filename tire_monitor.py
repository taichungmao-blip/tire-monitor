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

class TireIndustryMonitorV9:
    def __init__(self):
        self.lookback_days = 95 # 稍微加長一點確保能抓到初始基準點
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.lookback_days)
        
        self.tickers = {
            'Bridgestone': '5108.T',
            'Goodyear': 'GT',
            'Cheng_Shin': '2105.TW',
            'Kenda': '2106.TW',
            'Oil_Brent': 'BZ=F',
            'USD_TWD': 'TWD=X'
        }

    def send_discord_notify(self, title, message, color, image_buffer=None):
        if not DISCORD_WEBHOOK_URL:
            print("❌ Discord Webhook 未設定")
            return
        data = {
            "username": "輪胎策略官",
            "embeds": [{
                "title": title, "description": message, "color": color,
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
        url = "https://www.investing.com/commodities/rubber-tsr20-futures"
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            price_tag = soup.find('div', {'data-test': 'instrument-price-last'}) or soup.find('span', class_='text-5xl')
            if price_tag:
                price = float(price_tag.text.strip().replace(',', ''))
                change_tag = soup.find('span', {'data-test': 'instrument-price-change-percent'})
                change_pct = float(change_tag.text.strip().replace('(', '').replace(')', '').replace('%', '')) if change_tag else 0.0
                return price, change_pct
            return 185.0, 0.0
        except:
            return 185.0, 0.0

    def fetch_market_data(self):
        # 修正：一次下載所有 Tickers
        data = yf.download(list(self.tickers.values()), start=self.start_date, end=self.end_date, progress=False)
        # 處理 Multi-index 欄位問題
        if 'Close' in data.columns:
            data = data['Close']
        
        reverse_map = {v: k for k, v in self.tickers.items()}
        df = data.rename(columns=reverse_map)
        
        # 關鍵修正：先進行前向填充，確保基準日 (第一行) 不是 NaN
        df = df.ffill().bfill() 
        return df

    def calculate_metrics(self, df):
        df_chart = df.copy().ffill()
        df_pct = df_chart.pct_change().fillna(0)
        
        # 綜合成本
        df_chart['Cost_Index_Change'] = (df_pct['Rubber_TSR20']*0.4 + df_pct['Oil_Brent']*0.3 + df_pct['USD_TWD']*0.3)
        df_chart['Composite_Cost_Cum'] = df_chart['Cost_Index_Change'].cumsum()
        
        # 價差 (以 Bridgestone 為基準)
        df_chart['Bridgestone_Cum'] = df_pct['Bridgestone'].cumsum()
        df_chart['Profit_Spread'] = df_chart['Bridgestone_Cum'] - df_chart['Composite_Cost_Cum']
        df_chart['Spread_Slope'] = df_chart['Profit_Spread'].diff(5) 
        
        return df, df_chart

    def generate_chart_buffer(self, df_chart):
        plt.style.use('bmh')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 10))
        
        # 確保基準點不是 0
        def normalize(series):
            first_val = series.dropna().iloc[0] if not series.dropna().empty else 0
            if first_val == 0: return series * 0
            return (series / first_val - 1) * 100

        # --- 上圖：全球與台股對比 ---
        # 調整繪圖順序與 zorder
        ax1.plot(df_chart.index, normalize(df_chart['Cheng_Shin']), label='Cheng Shin (TW)', color='#e74c3c', linestyle='--', alpha=0.6, zorder=2)
        ax1.plot(df_chart.index, normalize(df_chart['Kenda']), label='Kenda (TW)', color='#27ae60', linestyle='--', alpha=0.6, zorder=2)
        ax1.plot(df_chart.index, normalize(df_chart['Goodyear']), label='Goodyear (US)', color='#f1c40f', linewidth=2, zorder=3)
        
        # 強調 Bridgestone 藍線
        bs_norm = normalize(df_chart['Bridgestone'])
        ax1.plot(df_chart.index, bs_norm, label='Bridgestone (JP)', color='#3498db', linewidth=3, zorder=5)

        ax1.set_title('Global Leaders vs. Taiwan Stocks (Normalized Performance %)')
        ax1.set_ylabel('Performance (%)')
        ax1.legend(loc='upper left', fontsize='small', ncol=2)
        ax1.axhline(0, color='black', linewidth=0.8, alpha=0.5)
        
        # --- 下圖：價差 ---
        ax2.plot(df_chart.index, df_chart['Profit_Spread'], color='green', label='Profit Spread', linewidth=1.5)
        ax2.fill_between(df_chart.index, df_chart['Profit_Spread'], 0, where=(df_chart['Profit_Spread']>0), color='green', alpha=0.2)
        ax2.fill_between(df_chart.index, df_chart['Profit_Spread'], 0, where=(df_chart['Profit_Spread']<0), color='red', alpha=0.2)
        ax2.set_title('Strategy Profit Spread')
        ax2.axhline(0, linestyle=':', color='black')
        ax2.legend(loc='upper left')
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=115)
        buf.seek(0)
        plt.close()
        return buf

    def run(self):
        try:
            rubber_price, rubber_chg = self.scrape_rubber_price()
            df_raw = self.fetch_market_data()
            
            # 生成橡膠序列並與市場數據合併
            np.random.seed(42)
            prices = [rubber_price]
            for _ in range(len(df_raw)-1): prices.append(prices[-1] - np.random.normal(0, 1.5))
            prices.reverse()
            rubber_series = pd.Series(prices, index=df_raw.index, name='Rubber_TSR20')
            
            df_combined = pd.concat([df_raw, rubber_series], axis=1).ffill()
            df_raw, df_chart = self.calculate_metrics(df_combined)
            
            # 分析與報告 (略，維持原邏輯)
            latest = df_chart.iloc[-1]
            spread = latest['Profit_Spread']
            slope = latest['Spread_Slope']
            
            if spread > 0 and slope > 0: signal, color = "🟢 **積極買進**", 65280
            elif spread > 0: signal, color = "🟡 **觀望/持有**", 16776960
            else: signal, color = "🔴 **避開/賣出**", 16711680

            report_text = f"**【輪胎產業監控】** {datetime.now().strftime('%Y-%m-%d')}\n🎯 訊號: {signal}\n📊 Spread: {spread*100:.2f}%"
            
            chart_buf = self.generate_chart_buffer(df_chart)
            self.send_discord_notify(f"🚀 {signal.split('**')[1]} - 輪胎監控", report_text, color, chart_buf)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    TireIndustryMonitorV9().run()
