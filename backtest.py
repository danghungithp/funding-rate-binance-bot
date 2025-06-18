import csv
from datetime import datetime
import glob

# Đọc dữ liệu funding rate và giá từ file CSV

def read_funding_data(filename):
    funding = []
    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Xử lý trường hợp có phần thập phân giây
            time_str = row['fundingTime'].split('.')[0]
            funding.append({
                'time': datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S'),
                'rate': float(row['fundingRate'])
            })
    return funding

def read_klines_data(filename):
    klines = []
    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            klines.append({
                'time': datetime.strptime(row['open_time'], '%Y-%m-%d %H:%M:%S'),
                'close': float(row['close'])
            })
    return klines

def find_price_at_time(klines, target_time):
    # Tìm giá đóng cửa gần nhất trước hoặc bằng thời điểm funding
    for k in reversed(klines):
        if k['time'] <= target_time:
            return k['close']
    return klines[0]['close']

def read_all_funding_data():
    funding_dict = {}
    for file in glob.glob('*_funding.csv'):
        symbol = file.split('_funding.csv')[0]
        funding_dict[symbol] = read_funding_data(file)
    return funding_dict

# Nâng cấp backtest: nhiều cặp, leverage, min_funding_rate, phí giao dịch, chọn cặp tốt nhất mỗi kỳ funding
def backtest_upgrade(funding_dict, klines_dict, deposit=9.9, leverage=3, min_funding_rate=0.0001, fee=0.0004, max_pairs=3):
    balance = deposit
    open_positions = {}
    results = []
    # Giả sử funding các cặp đồng bộ về thời gian (thực tế nên đồng bộ lại)
    all_times = sorted(set(t['time'] for v in funding_dict.values() for t in v))
    for t in all_times:
        # Chọn top max_pairs cặp funding rate cao nhất, dương và > min_funding_rate
        candidates = []
        for symbol, fundings in funding_dict.items():
            f = next((x for x in fundings if x['time'] == t), None)
            if f and f['rate'] > min_funding_rate:
                candidates.append((symbol, f['rate']))
        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[:max_pairs]
        # Đóng các vị thế funding rate thấp hoặc âm
        for symbol in list(open_positions.keys()):
            f = next((x for x in funding_dict[symbol] if x['time'] == t), None)
            if not f or f['rate'] <= min_funding_rate:
                # Đóng vị thế, trừ phí
                balance -= open_positions[symbol]['volume'] * open_positions[symbol]['price'] * fee
                del open_positions[symbol]
        # Mở vị thế mới cho các cặp tốt nhất
        for symbol, rate in selected:
            if symbol not in open_positions:
                price = find_price_at_time(klines_dict[symbol], t)
                volume = (balance / max_pairs) * leverage / price
                # Trừ phí mở lệnh
                balance -= volume * price * fee
                open_positions[symbol] = {'volume': volume, 'price': price}
        # Nhận funding cho các vị thế đang mở
        for symbol in open_positions:
            f = next((x for x in funding_dict[symbol] if x['time'] == t), None)
            if f:
                funding_pnl = open_positions[symbol]['volume'] * open_positions[symbol]['price'] * f['rate'] * leverage
                balance += funding_pnl
        results.append({'time': t, 'balance': balance, 'open_positions': list(open_positions.keys())})
    return results

if __name__ == "__main__":
    funding_dict = read_all_funding_data()
    klines_dict = {symbol: read_klines_data(f"{symbol}_klines.csv") for symbol in funding_dict}
    results = backtest_upgrade(funding_dict, klines_dict, deposit=9.9, leverage=3, min_funding_rate=0.0001, fee=0.0004, max_pairs=3)
    print("Kết quả backtest nâng cấp:")
    for r in results[-30:]:
        print(f"{r['time']} | Balance: {r['balance']:.5f} | Open: {r['open_positions']}")
    print(f"\nSố dư cuối cùng: {results[-1]['balance']:.5f} USDT")
