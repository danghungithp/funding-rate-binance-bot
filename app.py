from flask import Flask, render_template, request, redirect, url_for, session
import os
import datetime
import backtest_main_strategy
import threading
from config import api_key, api_secret
from binance.client import Client
import requests
import math

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
    first_iteration = True
    i = 0
    retry_count = 0
    max_retry = 5
    while bot_running:
        try:
            best_funding = get_best_positive_funding()
            first_coin = best_funding[i]
            while not check_spot_availability(first_coin['pair']):
                i += 1
                first_coin = best_funding[i]
            precision = get_precision(first_coin['pair'])
            trade_volume = round(get_trade_volume(first_coin['pair']), precision)
            if not check_open_positions(first_coin['pair']) and first_coin['rate'] > 1.0:
                if first_iteration:
                    client.futures_change_leverage(symbol=first_coin['pair'], leverage=1)
                    client.order_market_buy(symbol=first_coin['pair'], quantity=trade_volume)
                    client.futures_create_order(
                        symbol=first_coin['pair'],
                        side='SELL',
                        type='MARKET',
                        positionSide='SHORT',
                        quantity=trade_volume,
                        leverage=1
                    )
                else:
                    first_iteration = False
            if datetime.datetime.now() >= first_coin['next_funding_time']:
                j = 0
                actually_best_funding = get_best_positive_funding()
                actually_first_coin = actually_best_funding[j]
                while not check_spot_availability(actually_first_coin['pair']):
                    j += 1
                    actually_first_coin = actually_best_funding[j]
                if (first_coin['rate'] < actually_first_coin['rate'] and
                    first_coin['pair'] != actually_first_coin['pair'] and
                    (first_coin['rate'] < 0.5 or actually_first_coin['rate'] > 1.0)):
                    close_future_position(client, first_coin['pair'])
                    close_spot_position(first_coin['pair'])
                    spot_balance = client.get_asset_balance(asset='USDT')
                    futures_balance = client.futures_account_balance()
                    if float(spot_balance['free']) < 11:
                        transfer_amount = 11 - float(spot_balance['free'])
                        client.universal_transfer(type='UMFUTURE_MAIN', asset='USDT', amount=transfer_amount)
                    elif float(spot_balance['free']) > 11:
                        transfer_amount = float(spot_balance['free']) - 11
                        client.universal_transfer(type='MAIN_UMFUTURE', asset='USDT', amount=transfer_amount)
                    i = 0
                    while not check_spot_availability(first_coin['pair']):
                        i += 1
                        first_coin = best_funding[i]
                    precision = get_precision(first_coin['pair'])
                    trade_volume = round(get_trade_volume(first_coin['pair']), precision)
                    client.futures_change_leverage(symbol=first_coin['pair'], leverage=1)
                    client.futures_create_order(
                        symbol=first_coin['pair'],
                        side='SELL',
                        type='MARKET',
                        positionSide='SHORT',
                        quantity=trade_volume,
                        leverage=1
                    )
                    client.order_market_buy(symbol=first_coin['pair'], quantity=trade_volume)
                else:
                    time.sleep(1800)
            else:
                time.sleep(1800)
            retry_count = 0  # reset retry nếu thành công
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
        bot_error_msg=bot_error_msg
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

@app.route("/")
def index():
    return render_template(
        "index.html",
        positions=current_positions,
        history=trade_history,
        backtest_result=None,
        start_date=None,
        end_date=None
    )

@app.route("/backtest", methods=["POST"])
def backtest():
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    # Chạy backtest với khoảng thời gian được chọn
    results = backtest_main_strategy.run_backtest_with_time_range(start_date, end_date)
    return render_template(
        "index.html",
        positions=current_positions,
        history=trade_history,
        backtest_result=results,
        start_date=start_date,
        end_date=end_date
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
