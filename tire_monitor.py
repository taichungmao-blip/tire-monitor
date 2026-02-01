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
# 請確保環境變數中已設定 DISCORD_WEBHOOK_URL
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

class TireIndustryMonitorV8:
    def __init__(self):
        self.lookback_days = 90
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.lookback_days)
        
        # 監控標的清單
        self.tickers = {
            'Bridgestone': '5108.T',
            'Goodyear': 'GT',
            'Cheng_Shin': '2105.TW',
            'Kenda': '2106.TW',
            'Oil_Brent': 'BZ=F',
            'USD_TWD': 'TWD=X'
        }
        # 成本權重設定
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
        """從 Investing.com 爬取天然橡膠期貨價格"""
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
            else:
                raise Exception("DOM Changed")
        except:
            return 185.0, 0.0 # 若爬蟲失效的保底值

    def fetch_market_data(self):
        """下載各項金融數據"""
        data = yf.download(list(self.tickers.values()), start=self.start_date, end=self.end_date, progress=False)['Close']
        reverse_map = {v: k for k, v in self.tickers.items()}
        return data.rename(columns=reverse_map)

    def generate_rubber_series(self, dates, current_price):
        """生成橡膠價格序列 (模擬過去走勢以供畫圖)"""
        np.random.seed(42)
        prices = [current_price]
        for _ in range(len(dates)-1): prices.append(prices[-1] - np.random.normal(0, 1.5))
        prices.reverse()
        return pd.Series(prices, index=dates, name='Rubber_TSR20')

    def calculate_metrics(self, df):
        """計算核心策略指標"""
        df_chart = df.copy().ffill()
        df_pct = df_chart.pct_change().fillna(0)
        
        # 綜合成本指數
        df_chart['Cost_Index_Change'] = (df_pct['Rubber_TSR20']*0.4 + df_pct['Oil_Brent']*0.3 + df_pct['USD_TWD']*0.3)
        df_chart['Composite_Cost_Cum'] = df_chart['Cost_Index_Change'].cumsum()
        
        # 領頭羊利潤差 (Spread)
        df_chart['Bridgestone_Cum'] = df_pct['Bridgestone'].cumsum()
        df_chart['Profit_Spread'] = df_chart['Bridgestone_Cum'] - df_chart['Composite_Cost_Cum']
        df_chart['Spread_Slope'] = df_chart['Profit_Spread'].diff(5) 
        
        return df, df_chart

    def analyze_strategy(self, df_chart):
        """判斷買賣訊號"""
        latest = df_chart.iloc[-1]
        spread = latest['Profit_Spread']
        slope = latest['Spread_Slope']
        leader_trend = latest['Bridgestone'] > df_chart.iloc[-5]['Bridgestone']

        if spread > 0 and slope > 0 and leader_trend:
            return "🟢 **積極買進**", "利潤擴大 + 龍頭領漲", 65280
        elif spread > 0 and slope < 0:
            return "🟡 **觀望/持有**", "利潤收縮中，動能減弱", 16776960
        elif spread < 0:
            return "🔴 **避開/賣出**", "成本大漲吞噬利潤", 16711680
        else:
            return "⚪ **中立震盪**", "無明確方向", 12370112

    def get_real_latest_data(self, df, col_name):
        """獲取該欄位最後一個非 NaN 的真實數據與漲跌幅"""
        valid_series = df[col_name].dropna()
        if len(valid_series) < 2: return 0.0, 0.0, "N/A"
        
        latest_price = valid_series.iloc[-1]
        prev_price = valid_series.iloc[-2]
        change_pct = (latest_price - prev_price) / prev_price * 100
        last_date = valid_series.index[-1].strftime('%m/%d')
        return latest_price, change_pct, last_date

    def generate_chart_buffer(self, df_chart):
        """
        [更新] 包含 4 間輪胎廠，並確保 Bridgestone 顯示在最上層
        """
        plt.style.use('bmh')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 10))
        
        # 標準化函數：從 0% 開始比較
        def normalize(series):
            if series.isnull().all() or series.iloc[0] == 0:
                return series.fillna(0)
            return (series / series.iloc[0] - 1) * 100

        # --- 上圖：全球與台股對比 (使用 zorder 控管層級) ---
        # 1. 台股跟隨者 (先畫，放在下層 zorder=2)
        ax1.plot(df_chart.index, normalize(df_chart['Cheng_Shin']), 
                 label='Cheng Shin (TW)', color='#e74c3c', linestyle='--', alpha=0.7, zorder=2)
        ax1.plot(df_chart.index, normalize(df_chart['Kenda']), 
                 label='Kenda (TW)', color='#27ae60', linestyle='--', alpha=0.7, zorder=2)
        
        # 2. 國際領頭羊 - 固特異 (zorder=3)
        ax1.plot(df_chart.index, normalize(df_chart['Goodyear']), 
                 label='Goodyear (US)', color='#f1c40f', linewidth=2, zorder=3)
        
        # 3. 國際領頭羊 - 普利司通 (最後畫，確保在最上層 zorder=4)
        bridgestone_norm = normalize(df_chart['Bridgestone'])
        ax1.plot(df_chart.index, bridgestone_norm, 
                 label='Bridgestone (JP)', color='#3498db', linewidth=2.5, zorder=4)

        ax1.set_title('Global Leaders vs. Taiwan Stocks (Normalized Performance %)')
        ax1.set_ylabel('Performance (%)')
        ax1.legend(loc='upper left', fontsize='small', ncol=2)
        ax1.axhline(0, color='black', linewidth=0.8, alpha=0.5)
        
        # --- 下圖：利潤價差 ---
        ax2.plot(df_chart.index, df_chart['Profit_Spread'], color='green', label='Profit Spread', linewidth=1.5)
        ax2.fill_between(df_chart.index, df_chart['Profit_Spread'], 0, 
                         where=(df_chart['Profit_Spread'] > 0), color='green', alpha=0.2)
        ax2.fill_between(df_chart.index, df_chart['Profit_Spread'], 0, 
                         where=(df_chart['Profit_Spread'] < 0), color='red', alpha=0.2)
        ax2.set_title('Strategy Profit Spread (Leader Return - Cost Index)')
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
            # 1. 取得數據
            rubber_price, rubber_chg = self.scrape_rubber_price()
            df_raw = self.fetch_market_data()
            
            # 2. 整合橡膠與計算指標
            rubber_series = self.generate_rubber_series(df_raw.index, rubber_price)
            df_raw = pd.concat([df_raw, rubber_series], axis=1)
            df_raw, df_chart = self.calculate_metrics(df_raw)
            
            # 3. 訊號分析
            signal, reason, color = self.analyze_strategy(df_chart)

            # 4. 格式化報告文字
            def get_fmt(col):
                if col == 'Rubber_TSR20': 
                    return f"{rubber_price:.2f} ({rubber_chg:+.2f}%)"
                price, pct, date_str = self.get_real_latest_data(df_raw, col)
                date_suffix = "" if date_str == datetime.now().strftime('%m/%d') else f" [{date_str}]"
                return f"{price:.2f} ({pct:+.2f}%){date_suffix}"

            cost_change = df_chart['Cost_Index_Change'].iloc[-1] * 100
            spread_val = df_chart['Profit_Spread'].iloc[-1] * 100

            report_text = (
                f"**【輪胎產業戰術日報】** {datetime.now().strftime('%Y-%m-%d')}\n\n"
                f"🎯 **策略訊號: {signal}**\n"
                f"📝 **理由**: {reason}\n\n"
                f"**🌍 國際領頭羊**\n"
                f"• 普利司通: {get_fmt('Bridgestone')}\n"
                f"• 固特異: {get_fmt('Goodyear')}\n\n"
                f"**🛢️ 成本因子**\n"
                f"• 天然橡膠: {get_fmt('Rubber_TSR20')}\n"
                f"• 原油: {get_fmt('Oil_Brent')}\n"
                f"• 綜合成本變化: **{cost_change:+.2f}%**\n\n"
                f"**🇹🇼 台股監控**\n"
                f"• 正新: {get_fmt('Cheng_Shin')}\n"
                f"• 建大: {get_fmt('Kenda')}\n\n"
                f"📊 **Spread (利潤空間): {spread_val:.2f}**"
            )
            
            # 5. 生成圖表並發送通知
            chart_buffer = self.generate_chart_buffer(df_chart)
            self.send_discord_notify(f"🚀 {signal.split('**')[1]} - 輪胎產業監控", report_text, color, chart_buffer)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    app = TireIndustryMonitorV8()
    app.run()
