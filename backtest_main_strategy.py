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

def backtest_main_strategy(funding_dict, klines_dict, deposit=9.9, fee=0.0004, funding_threshold=0.003):
    balance = deposit
    position = None
    results = []
    trade_log = []
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
        # Nếu chưa có vị thế và funding > funding_threshold
        if not position and first_coin['rate'] > funding_threshold:
            volume = balance / price
            balance -= volume * price * fee * 2  # phí mở 2 lệnh
            position = {'pair': first_coin['pair'], 'volume': volume, 'price': price, 'rate': first_coin['rate']}
            trade_log.append({'time': t, 'action': 'OPEN', 'pair': first_coin['pair'], 'side': 'BUY/SELL', 'volume': volume, 'price': price})
        # Đến kỳ funding mới, kiểm tra có cặp tốt hơn không
        elif position and (position['pair'] != first_coin['pair'] and first_coin['rate'] > funding_threshold and first_coin['rate'] > position['rate']):
            # Đóng vị thế cũ
            balance -= position['volume'] * price * fee * 2  # phí đóng 2 lệnh
            trade_log.append({'time': t, 'action': 'CLOSE', 'pair': position['pair'], 'side': 'SELL/BUY', 'volume': position['volume'], 'price': price})
            position = None
            # Mở vị thế mới
            volume = balance / price
            balance -= volume * price * fee * 2
            position = {'pair': first_coin['pair'], 'volume': volume, 'price': price, 'rate': first_coin['rate']}
            trade_log.append({'time': t, 'action': 'OPEN', 'pair': first_coin['pair'], 'side': 'BUY/SELL', 'volume': volume, 'price': price})
        # Nhận funding nếu đang giữ vị thế
        if position and position['pair'] == first_coin['pair']:
            funding_pnl = position['volume'] * price * first_coin['rate']
            balance += funding_pnl
            position['rate'] = first_coin['rate']
        results.append({'time': t, 'balance': balance, 'pair': position['pair'] if position else None})
    return results, trade_log

def calc_drawdowns(equity_curve):
    max_drawdown = 0
    min_drawdown = 0
    drawdowns = []
    peak = equity_curve[0]
    for x in equity_curve:
        if x > peak:
            peak = x
        dd = (x - peak) / peak
        drawdowns.append(dd)
        if dd < min_drawdown:
            min_drawdown = dd
        if dd < max_drawdown:
            max_drawdown = dd
    avg_drawdown = sum(drawdowns) / len(drawdowns)
    return abs(max_drawdown), abs(avg_drawdown), abs(min_drawdown)

def run_backtest_with_time_range(start_date, end_date, funding_threshold=0.003, deposit=9.9, target_annual_return=100, fee=0.0004):
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
    results, trade_log = backtest_main_strategy(funding_dict, klines_dict, deposit=deposit, fee=fee, funding_threshold=funding_threshold)
    # Tính toán các chỉ số hiệu suất
    equity_curve = [x['balance'] for x in results]
    if len(equity_curve) < 2:
        return {
            'history': results,
            'trade_log': trade_log,
            'annualized_return': 0,
            'required_capital': 0,
            'max_drawdown': 0,
            'avg_drawdown': 0,
            'min_drawdown': 0,
            'min_capital': deposit,
            'suggested_leverage': 1,
            'suggested_volume': 0
        }
    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
    days = (results[-1]['time'] - results[0]['time']).days
    if days == 0:
        annualized_return = total_return
    else:
        annualized_return = (1 + total_return) ** (365/days) - 1
    # Số vốn cần có để đạt target annual return (nếu giữ nguyên logic)
    required_capital = 0
    if annualized_return > 0:
        required_capital = deposit * (target_annual_return/100) / annualized_return
    # Drawdown
    max_dd, avg_dd, min_dd = calc_drawdowns(equity_curve)
    # Vốn tối thiểu và đòn bẩy khuyến nghị (giả sử max_dd là rủi ro lớn nhất)
    min_capital = deposit / (1 - max_dd) if max_dd < 1 else deposit
    suggested_leverage = 1 / (1 - max_dd) if max_dd < 1 else 1
    # Gợi ý khối lượng tối ưu: dùng tối đa 1/(1-max_dd) lần vốn (giả sử không margin call)
    suggested_volume = deposit / (1 - max_dd) if max_dd < 1 else deposit
    return {
        'history': results,
        'trade_log': trade_log,
        'annualized_return': annualized_return,
        'required_capital': required_capital,
        'max_drawdown': max_dd,
        'avg_drawdown': avg_dd,
        'min_drawdown': min_dd,
        'min_capital': min_capital,
        'suggested_leverage': suggested_leverage,
        'suggested_volume': suggested_volume
    }

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
