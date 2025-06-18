import csv
from datetime import datetime

def read_funding_data(filename):
    funding = []
    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
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
    for k in reversed(klines):
        if k['time'] <= target_time:
            return k['close']
    return klines[0]['close']

def get_best_positive_funding(funding_dict, t):
    # Lấy top 10 cặp funding rate dương tại thời điểm t
    candidates = []
    for symbol, fundings in funding_dict.items():
        f = next((x for x in fundings if x['time'] == t), None)
        if f and f['rate'] > 0:
            candidates.append((symbol, f['rate']))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:10]

def backtest_main_strategy(funding_dict, klines_dict, deposit=9.9, fee=0.0004):
    balance = deposit
    position = None
    results = []
    all_times = sorted(set(t['time'] for v in funding_dict.values() for t in v))
    for t in all_times:
        # Lấy top funding dương
        best_funding = get_best_positive_funding(funding_dict, t)
        # Chọn cặp đầu tiên có dữ liệu giá (giả lập spot available)
        first_coin = None
        for symbol, rate in best_funding:
            if symbol in klines_dict:
                first_coin = {'pair': symbol, 'rate': rate}
                break
        if not first_coin:
            results.append({'time': t, 'balance': balance, 'pair': None})
            continue
        price = find_price_at_time(klines_dict[first_coin['pair']], t)
        # Nếu chưa có vị thế và funding > 1%
        if not position and first_coin['rate'] > 0.01:
            volume = balance / price
            balance -= volume * price * fee * 2  # phí mở 2 lệnh
            position = {'pair': first_coin['pair'], 'volume': volume, 'price': price}
        # Đến kỳ funding mới, kiểm tra có cặp tốt hơn không
        elif position and (position['pair'] != first_coin['pair'] and first_coin['rate'] > 0.01 and first_coin['rate'] > position['rate']):
            # Đóng vị thế cũ
            balance -= position['volume'] * price * fee * 2  # phí đóng 2 lệnh
            position = None
            # Mở vị thế mới
            volume = balance / price
            balance -= volume * price * fee * 2
            position = {'pair': first_coin['pair'], 'volume': volume, 'price': price}
        # Nhận funding nếu đang giữ vị thế
        if position and position['pair'] == first_coin['pair']:
            funding_pnl = position['volume'] * price * first_coin['rate']
            balance += funding_pnl
            position['rate'] = first_coin['rate']
        results.append({'time': t, 'balance': balance, 'pair': position['pair'] if position else None})
    return results

def run_backtest_with_time_range(start_date, end_date):
    import glob
    from datetime import datetime
    funding_dict = {}
    klines_dict = {}
    for file in glob.glob('*_funding.csv'):
        symbol = file.split('_funding.csv')[0]
        funding_dict[symbol] = read_funding_data(file)
        klines_dict[symbol] = read_klines_data(f'{symbol}_klines.csv')
    # Lọc lại funding theo khoảng thời gian
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    for symbol in funding_dict:
        funding_dict[symbol] = [x for x in funding_dict[symbol] if start_dt <= x['time'] <= end_dt]
    for symbol in klines_dict:
        klines_dict[symbol] = [x for x in klines_dict[symbol] if start_dt <= x['time'] <= end_dt]
    results = backtest_main_strategy(funding_dict, klines_dict)
    return results

if __name__ == "__main__":
    # Đọc tất cả funding và giá các cặp có file
    import glob
    funding_dict = {}
    klines_dict = {}
    for file in glob.glob('*_funding.csv'):
        symbol = file.split('_funding.csv')[0]
        funding_dict[symbol] = read_funding_data(file)
        klines_dict[symbol] = read_klines_data(f'{symbol}_klines.csv')
    results = backtest_main_strategy(funding_dict, klines_dict)
    print("Kết quả backtest chiến lược main.py:")
    for r in results[-30:]:
        print(f"{r['time']} | Balance: {r['balance']:.5f} | Pair: {r['pair']}")
    print(f"\nSố dư cuối cùng: {results[-1]['balance']:.5f} USDT")
