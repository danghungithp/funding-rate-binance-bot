from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import datetime
import backtest_main_strategy
import threading
from config import api_key, api_secret
from binance.client import Client
import requests
import math
import fetch_binance_data

app = Flask(__name__)
app.secret_key = 'super_secret_key_123'  # Đổi secret key khi dùng thật

# Biến trạng thái bot và dữ liệu mô phỏng
bot_running = False
bot_thread = None
bot_status = "stopped"  # running, stopped, error
bot_error_msg = ""
current_positions = []
trade_history = []
profit_loss = 0.0
asset_total = 0.0

# Thêm biến cấu hình funding rate threshold cho bot và backtest
funding_threshold = 0.003  # mặc định 0.3%

client = Client(api_key, api_secret)

# --- Logic lấy trạng thái thực tế từ Binance ---
def get_real_positions():
    # Lấy vị thế futures
    futures_positions = client.futures_position_information()
    positions = []
    for pos in futures_positions:
        amt = float(pos['positionAmt'])
        if amt != 0:
            side = 'LONG' if amt > 0 else 'SHORT'
            entry = float(pos['entryPrice'])
            positions.append({
                'pair': pos['symbol'],
                'side': side,
                'volume': abs(amt),
                'entry': entry
            })
    return positions

def get_real_trade_history(limit=10):
    # Lấy lịch sử giao dịch gần nhất trên futures
    trades = client.futures_account_trades()
    history = []
    for t in trades[-limit:]:
        history.append({
            'time': datetime.datetime.fromtimestamp(t['time']/1000).strftime('%Y-%m-%d %H:%M:%S'),
            'pair': t['symbol'],
            'type': 'BUY' if t['side']=='BUY' else 'SELL',
            'volume': float(t['qty']),
            'price': float(t['price'])
        })
    return history[::-1]

def get_real_profit_and_asset():
    # Lấy tổng tài sản và lãi/lỗ chưa thực hiện
    futures_balance = client.futures_account_balance()
    spot_balance = client.get_asset_balance(asset='USDT')
    total = 0.0
    for b in futures_balance:
        if b['asset'] == 'USDT':
            total += float(b['balance'])
    if spot_balance:
        total += float(spot_balance['free'])
    # Lãi/lỗ chưa thực hiện (tạm thời = 0, có thể lấy từ futures_account nếu cần)
    return 0.0, total

def run_bot():
    global bot_running, bot_status, bot_error_msg
    bot_running = True
    bot_status = "running"
    bot_error_msg = ""
    import time
    from binance.exceptions import BinanceAPIException
    max_retry = 5
    retry_count = 0
    open_position = None
    while bot_running:
        try:
            best_funding = get_best_positive_funding()
            if not best_funding:
                time.sleep(1800)
                continue
            first_coin = best_funding[0]
            symbol = first_coin['pair']
            rate = first_coin['rate']
            if rate < funding_threshold:
                time.sleep(1800)
                continue
            precision = get_precision(symbol)
            price = get_current_price(symbol)
            # Lấy tổng vốn khả dụng USDT
            spot_balance = float(client.get_asset_balance(asset='USDT')['free'])
            futures_balance = 0.0
            for b in client.futures_account_balance():
                if b['asset'] == 'USDT':
                    futures_balance = float(b['balance'])
            total_capital = spot_balance + futures_balance
            volume = round(total_capital / price, precision)
            # Nếu chưa có vị thế thì mở mới
            if not open_position or open_position['symbol'] != symbol or open_position['volume'] == 0:
                client.futures_change_leverage(symbol=symbol, leverage=1)
                client.order_market_buy(symbol=symbol, quantity=volume)
                client.futures_create_order(
                    symbol=symbol,
                    side='SELL',
                    type='MARKET',
                    positionSide='SHORT',
                    quantity=volume,
                    leverage=1
                )
                open_position = {'symbol': symbol, 'volume': volume, 'entry': price, 'rate': rate}
            else:
                open_position['rate'] = rate
            # Đóng vị thế nếu funding không còn tốt hoặc có cặp tốt hơn
            if open_position and (open_position['symbol'] != symbol or rate < funding_threshold):
                close_future_position(client, open_position['symbol'])
                close_spot_position(open_position['symbol'])
                open_position['volume'] = 0
            time.sleep(1800)
            retry_count = 0
        except BinanceAPIException as e:
            bot_status = "error"
            bot_error_msg = f'Binance API error: {e}'
            print(bot_error_msg)
            retry_count += 1
            if retry_count >= max_retry:
                bot_running = False
                break
            time.sleep(60)
        except Exception as e:
            bot_status = "error"
            bot_error_msg = f'Bot error: {e}'
            print(bot_error_msg)
            retry_count += 1
            if retry_count >= max_retry:
                bot_running = False
                break
            time.sleep(60)
    if not bot_running:
        bot_status = "stopped"
    elif bot_status == "error":
        bot_status = "error"

def stop_bot():
    global bot_running, bot_status
    bot_running = False
    bot_status = "stopped"

def close_all_positions():
    global current_positions
    current_positions.clear()

# --- Các hàm logic giao dịch thực tế từ main.py ---
def check_spot_availability(symbol):
    tickers = client.get_all_tickers()
    for ticker in tickers:
        if ticker['symbol'] == symbol:
            return True
    return False

def get_precision(symbol):
    info = client.futures_exchange_info()
    for asset in info['symbols']:
        if asset['symbol'] == symbol:
            return asset['quantityPrecision']
    return None

def get_trade_volume(pair):
    precision = get_precision(pair)
    price = get_current_price(pair)
    volume = round(9.9 / price, precision)
    return volume

def get_current_price(symbol):
    ticker = client.get_ticker(symbol=symbol)
    return float(ticker['lastPrice'])

def check_open_positions(symbol):
    positions = client.futures_position_information(symbol=symbol)
    for position in positions:
        if float(position['positionAmt']) != 0:
            return True
    return False

def get_best_positive_funding():
    response = requests.get('https://fapi.binance.com/fapi/v1/premiumIndex')
    data = response.json()
    positive_funding = [item for item in data if float(item['lastFundingRate']) > 0]
    sorted_pairs = sorted(positive_funding, key=lambda x: float(x['lastFundingRate']), reverse=True)
    top_10_pairs = sorted_pairs[:10]
    result = []
    for pair in top_10_pairs:
        next_funding_time = datetime.datetime.fromtimestamp(int(pair['nextFundingTime']) / 1000)
        rate = float(pair['lastFundingRate']) * 100
        result.append({
            'pair': pair['symbol'],
            'rate': rate,
            'next_funding_time': next_funding_time
        })
    return result

def close_future_position(client, symbol):
    open_positions = client.futures_position_information(symbol=symbol)
    for position in open_positions:
        if float(position['positionAmt']) != 0:
            quantity = abs(float(position['positionAmt']))
            side = Client.SIDE_SELL if float(position['positionAmt']) > 0 else Client.SIDE_BUY
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type=Client.ORDER_TYPE_MARKET,
                quantity=quantity,
                positionSide="BOTH" if side == Client.SIDE_SELL else "SHORT"
            )
            return order
    return None

def close_spot_position(symbol):
    asset = symbol[:-4]
    free_balance = client.get_asset_balance(asset=asset)['free']
    info = client.get_symbol_info(symbol)
    step_size = 0.0
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            step_size = float(f['stepSize'])
    quantity = math.floor(float(free_balance) / step_size) * step_size
    if quantity > 0:
        client.order_market_sell(symbol=symbol, quantity=quantity)

def get_funding_threshold():
    global funding_threshold
    return funding_threshold

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'Admin' and password == 'Danghungit@85':
            session['logged_in'] = True
            return redirect(url_for('running'))
        else:
            return render_template('login.html', error='Sai tài khoản hoặc mật khẩu!')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/running')
def running():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    # Lấy dữ liệu thực tế từ Binance
    try:
        positions = get_real_positions()
        history = get_real_trade_history()
        profit_loss, asset_total = get_real_profit_and_asset()
    except Exception as e:
        positions = []
        history = []
        profit_loss = 0.0
        asset_total = 0.0
    return render_template(
        'running.html',
        positions=positions,
        history=history,
        profit_loss=profit_loss,
        asset_total=asset_total,
        bot_running=bot_running,
        bot_status=bot_status,
        bot_error_msg=bot_error_msg,
        funding_threshold=get_funding_threshold()
    )

@app.route('/start_bot', methods=['POST'])
def start_bot():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    global bot_thread, bot_running
    if not bot_running:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
    return redirect(url_for('running'))

@app.route('/stop_bot', methods=['POST'])
def stop_bot_route():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    stop_bot()
    return redirect(url_for('running'))

@app.route('/close_positions', methods=['POST'])
def close_positions():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    close_all_positions()
    return redirect(url_for('running'))

@app.route('/set_funding_threshold', methods=['POST'])
def set_funding_threshold():
    global funding_threshold
    try:
        value = float(request.form.get('funding_threshold', '0.003'))
        funding_threshold = value
        return jsonify({'success': True, 'value': funding_threshold})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route("/")
def index():
    return render_template(
        "index.html",
        positions=current_positions,
        history=trade_history,
        backtest_result=None,
        start_date=None,
        end_date=None,
        funding_threshold=funding_threshold,
        deposit=9.9,
        target_annual_return=100,
        fee=0.0004
    )

@app.route("/backtest", methods=["POST"])
def backtest():
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    funding_thres = request.form.get("funding_threshold", funding_threshold)
    try:
        funding_thres = float(funding_thres)
    except:
        funding_thres = funding_threshold
    deposit = request.form.get("deposit", 9.9)
    try:
        deposit = float(deposit)
    except:
        deposit = 9.9
    target_annual_return = request.form.get("target_annual_return", 100)
    try:
        target_annual_return = float(target_annual_return)
    except:
        target_annual_return = 100
    fee = request.form.get("fee", 0.0004)
    try:
        fee = float(fee)
    except:
        fee = 0.0004
    # Luôn tải dữ liệu mới từ API trước khi backtest
    fetch_binance_data.main_download()
    results = backtest_main_strategy.run_backtest_with_time_range(
        start_date, end_date, funding_thres, deposit, target_annual_return, fee
    )
    return render_template(
        "index.html",
        positions=current_positions,
        history=trade_history,
        backtest_result=results,
        start_date=start_date,
        end_date=end_date,
        funding_threshold=funding_thres,
        deposit=deposit,
        target_annual_return=target_annual_return,
        fee=fee
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
