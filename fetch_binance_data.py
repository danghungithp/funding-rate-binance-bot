import requests
import csv
import datetime

# Danh sách các cặp muốn lấy dữ liệu (Top 10 funding rate dương cao nhất 17/06/2025)
symbols = [
    "MEMEFIUSDT", "NEIROETHUSDT", "HYPEUSDT", "1000000BOBUSDT", "1000RATSUSDT",
    "KAVAUSDT", "SUIUSDC", "BELUSDT", "GMTUSDT", "DASHUSDT"
]

def fetch_funding_rate(symbol, limit=1000):
    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit={limit}"
    response = requests.get(url)
    data = response.json()
    return data

def fetch_klines(symbol, interval="1h", limit=1000):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    response = requests.get(url)
    data = response.json()
    return data

def save_funding_to_csv(data, filename):
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["fundingTime", "fundingRate"])
        for entry in data:
            time_str = datetime.datetime.fromtimestamp(int(entry["fundingTime"])/1000)
            writer.writerow([time_str, entry["fundingRate"]])

def save_klines_to_csv(data, filename):
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["open_time", "open", "high", "low", "close", "volume"])
        for entry in data:
            time_str = datetime.datetime.fromtimestamp(int(entry[0])/1000)
            writer.writerow([time_str, entry[1], entry[2], entry[3], entry[4], entry[5]])

def main_download():
    for symbol in symbols:
        print(f"Đang tải dữ liệu cho {symbol}...")
        funding_data = fetch_funding_rate(symbol)
        save_funding_to_csv(funding_data, f"{symbol}_funding.csv")
        klines_data = fetch_klines(symbol)
        save_klines_to_csv(klines_data, f"{symbol}_klines.csv")
    print("Đã lưu dữ liệu funding rate và giá về file CSV cho tất cả các cặp.")

if __name__ == "__main__":
    for symbol in symbols:
        print(f"Đang tải dữ liệu cho {symbol}...")
        funding_data = fetch_funding_rate(symbol)
        save_funding_to_csv(funding_data, f"{symbol}_funding.csv")
        klines_data = fetch_klines(symbol)
        save_klines_to_csv(klines_data, f"{symbol}_klines.csv")
    print("Đã lưu dữ liệu funding rate và giá về file CSV cho tất cả các cặp.")
