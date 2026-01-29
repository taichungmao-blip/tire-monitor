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

class TireIndustryMonitorV7:
    def __init__(self):
        self.lookback_days = 90
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.lookback_days)
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
            return 185.0, 0.0

    def fetch_market_data(self):
        # 這裡不進行 ffill，保留 NaN 以便後續判斷真實收盤日
        data = yf.download(list(self.tickers.values()), start=self.start_date, end=self.end_date, progress=False)['Close']
        reverse_map = {v: k for k, v in self.tickers.items()}
        return data.rename(columns=reverse_map)

    def generate_rubber_series(self, dates, current_price):
        np.random.seed(42)
        prices = [current_price]
        for _ in range(len(dates)-1): prices.append(prices[-1] - np.random.normal(0, 1.5))
        prices.reverse()
        return pd.Series(prices, index=dates, name='Rubber_TSR20')

    def calculate_metrics(self, df):
        # 為了畫圖連續性，這裡產生一個 copy 做 ffill，但不影響原始 df 的數值判讀
        df_chart = df.copy().ffill()
        
        df_pct = df_chart.pct_change().fillna(0)
        df_chart['Cost_Index_Change'] = (df_pct['Rubber_TSR20']*0.4 + df_pct['Oil_Brent']*0.3 + df_pct['USD_TWD']*0.3)
        df_chart['Composite_Cost_Cum'] = df_chart['Cost_Index_Change'].cumsum()
        df_chart['Bridgestone_Cum'] = df_pct['Bridgestone'].cumsum()
        df_chart['Profit_Spread'] = df_chart['Bridgestone_Cum'] - df_chart['Composite_Cost_Cum']
        df_chart['Spread_Slope'] = df_chart['Profit_Spread'].diff(5) 
        
        return df, df_chart # 回傳兩個：原始含 NaN 的 (做報告用) 和 填補過的 (畫圖用)

    def analyze_strategy(self, df_chart):
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
        """
        [關鍵修正]
        獲取該欄位「最後一個非 NaN」的真實數據與漲跌幅
        解決 ffill 導致的 0.00% 問題
        """
        valid_series = df[col_name].dropna()
        if len(valid_series) < 2:
            return 0.0, 0.0, "N/A"
        
        latest_price = valid_series.iloc[-1]
        prev_price = valid_series.iloc[-2]
        change_pct = (latest_price - prev_price) / prev_price * 100
        last_date = valid_series.index[-1].strftime('%m/%d')
        
        return latest_price, change_pct, last_date

    def generate_chart_buffer(self, df_chart):
        plt.style.use('bmh')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        
        ax1.plot(df_chart.index, df_chart['Bridgestone'], label='Bridgestone (Leader)', color='#3498db')
        ax1_r = ax1.twinx()
        ax1_r.plot(df_chart.index, df_chart['Cheng_Shin'], label='Cheng Shin (Follower)', color='#e74c3c', linestyle='--')
        ax1.set_title('Leader-Lag: Bridgestone vs Cheng Shin')
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax1_r.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        
        ax2.plot(df_chart.index, df_chart['Profit_Spread'], color='green', label='Profit Spread')
        ax2.fill_between(df_chart.index, df_chart['Profit_Spread'], 0, where=(df_chart['Profit_Spread']>0), color='green', alpha=0.3)
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
            rubber_price, rubber_chg = self.scrape_rubber_price()
            df_raw = self.fetch_market_data() # 原始資料，含 NaN
            
            # 畫圖用的 DF 需填充
            rubber_series = self.generate_rubber_series(df_raw.index, rubber_price)
            df_raw = pd.concat([df_raw, rubber_series], axis=1)
            
            # 分別處理報告用(df_raw) 與 畫圖用(df_chart)
            df_raw, df_chart = self.calculate_metrics(df_raw)
            
            signal, reason, color = self.analyze_strategy(df_chart)

            # 輔助函數：顯示數據與日期
            def get_fmt(col):
                if col == 'Rubber_TSR20': 
                    # 橡膠比較特殊，是爬蟲抓的單點
                    return f"{rubber_price:.2f} ({rubber_chg:+.2f}%)"
                
                price, pct, date_str = self.get_real_latest_data(df_raw, col)
                # 如果日期不是今天，標註一下日期
                date_suffix = "" if date_str == datetime.now().strftime('%m/%d') else f" [{date_str}]"
                return f"{price:.2f} ({pct:+.2f}%){date_suffix}"

            # 綜合成本直接用 chart 的最新值即可 (因為是合成指標)
            cost_change = df_chart['Cost_Index_Change'].iloc[-1] * 100
            spread_val = df_chart['Profit_Spread'].iloc[-1] * 100

            report_text = (
                f"**【輪胎產業戰術日報】** {datetime.now().strftime('%Y-%m-%d')}\n\n"
                f"🎯 **策略訊號: {signal}**\n"
                f"📝 **理由**: {reason}\n\n"
                
                f"**🇺🇸 國際指標**\n"
                f"• 普利司通: {get_fmt('Bridgestone')}\n"
                f"• 固特異: {get_fmt('Goodyear')}\n\n"
                
                f"**🛢️ 成本因子**\n"
                f"• 天然橡膠: {get_fmt('Rubber_TSR20')}\n"
                f"• 原油: {get_fmt('Oil_Brent')}\n"
                f"• 綜合成本變化: **{cost_change:+.2f}%**\n\n"
                
                f"**🇹🇼 台股監控**\n"
                f"• 正新: {get_fmt('Cheng_Shin')}\n"
                f"• 建大: {get_fmt('Kenda')}\n\n"
                
                f"📊 **Spread: {spread_val:.2f}**"
            )
            
            chart_buffer = self.generate_chart_buffer(df_chart)
            self.send_discord_notify(f"🚀 {signal.split('**')[1]} - 輪胎監控", report_text, color, chart_buffer)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    app = TireIndustryMonitorV7()
    app.run()
