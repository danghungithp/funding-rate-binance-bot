from config import api_key, api_secret
from binance.client import Client
import requests
import datetime
import time
import math

client = Client(api_key, api_secret)

deposit = 9.9  # Депозит USDT

first_iteration = True

i = 0

def check_internet():
    url = "http://www.google.com"
    timeout = 5
    try:
        _ = requests.get(url, timeout=timeout)
        return True
    except requests.ConnectionError:
        print("Интернет отсутствует.")
        return False

def check_spot_availability(symbol):
    tickers = client.get_all_tickers()
    for ticker in tickers:
        if ticker['symbol'] == symbol:
            return True
    return False

def get_current_price(symbol):
    ticker = client.get_ticker(symbol=symbol)
    current_price = float(ticker['lastPrice'])
    return current_price

def get_trade_volume(pair):
    precision = get_precision(first_coin['pair'])
    volume = round(deposit / get_current_price(pair), precision)
    print(f"Торговый объем: {volume}")
    return volume

def close_future_position(client: Client, symbol: str):
    # Получаем информацию о всех открытых позициях
    open_positions = client.futures_position_information(symbol=symbol)

    for position in open_positions:
        # Если позиция открыта, закрываем её
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

# Закрытие спотовой позиции
def close_spot_position(symbol):
    # Получение информации о текущей позиции
    asset = symbol[:-4]
    free_balance = client.get_asset_balance(asset=asset)['free']

    # Получение информации о лоте
    info = client.get_symbol_info(symbol)
    step_size = 0.0
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            step_size = float(f['stepSize'])

    # Округление до допустимого значения
    quantity = math.floor(float(free_balance) / step_size) * step_size

    # Закрытие позиции
    if quantity > 0:
        client.order_market_sell(symbol=symbol, quantity=quantity)
        
def get_precision(symbol):
    info = client.futures_exchange_info()
    for asset in info['symbols']:
        if asset['symbol'] == symbol:
            return asset['quantityPrecision']
    return None

def get_funding_interval(symbol):
    response = requests.get(f'https://fapi.binance.com/fapi/v1/fundingInfo?symbol={symbol}')
    data = response.json()
    return data[0]['fundingIntervalHours']

def get_best_positive_funding():
    response = requests.get('https://fapi.binance.com/fapi/v1/premiumIndex')
    data = response.json()
    positive_funding = [item for item in data if float(item['lastFundingRate']) > 0]
    sorted_pairs = sorted(positive_funding, key=lambda x: float(x['lastFundingRate']), reverse=True)
    top_10_pairs = sorted_pairs[:10]
    result = []
    for pair in top_10_pairs:
        next_funding_time = datetime.datetime.fromtimestamp(int(pair['nextFundingTime']) / 1000)
        funding_interval = get_funding_interval(pair['symbol'])
        rate = float(pair['lastFundingRate']) * 100
        if funding_interval == 4:
            rate *= 2
        result.append({
            'pair': pair['symbol'],
            'rate': rate,
            'next_funding_time': next_funding_time
        })
    return result

def get_specific_pair_funding(symbol):
    response = requests.get('https://fapi.binance.com/fapi/v1/premiumIndex')
    data = response.json()
    pair_data = next((item for item in data if item["symbol"] == symbol), None)
    if pair_data is not None:
        next_funding_time = datetime.datetime.fromtimestamp(int(pair_data['nextFundingTime']) / 1000)
        return pair_data['symbol'], float(pair_data['lastFundingRate']) * 100, next_funding_time
    else:
        return None

def check_open_positions(symbol):
    positions = client.futures_position_information(symbol=symbol)
    for position in positions:
        if float(position['positionAmt']) != 0:
            return True
    return False

best_funding = get_best_positive_funding()
first_coin = best_funding[i]

while not check_spot_availability(first_coin['pair']):
    i += 1
    first_coin = best_funding[i]

print(first_coin['pair'], first_coin['rate'], first_coin['next_funding_time'])

while True:
    if check_internet:
        precision = get_precision(first_coin['pair'])
        trade_volume = round(get_trade_volume(first_coin['pair']), precision)
        if not check_open_positions(first_coin['pair']) and first_coin['rate'] > 1.0:
            if first_iteration:
                client.futures_change_leverage(symbol=first_coin['pair'], leverage=1)
                order = client.order_market_buy(symbol=first_coin['pair'], quantity=trade_volume)
                sell_market = client.futures_create_order(symbol=first_coin['pair'], side='SELL', type='MARKET', positionSide='SHORT', quantity=trade_volume, leverage=1)
            else:
                first_iteration = False

        if datetime.datetime.now() >= first_coin['next_funding_time']:
        
            j = 0
        
            actually_best_funding = get_best_positive_funding()
            actually_first_coin = actually_best_funding[j]
            print(actually_first_coin['pair'], actually_first_coin['rate'], actually_first_coin['next_funding_time'])

            while not check_spot_availability(actually_first_coin['pair']):
                j += 1
                actually_first_coin = actually_best_funding[j]

            if first_coin['rate'] < actually_first_coin['rate'] and first_coin['pair'] != actually_first_coin['pair'] and (first_coin['rate'] < 0.5 or actually_first_coin['rate'] > 1.0):
                close_future_position(client, first_coin['pair'])
                close_spot_position(first_coin['pair'])
                
                # Получить спотовый баланс
                spot_balance = client.get_asset_balance(asset='USDT')

                # Получить фьючерсный баланс
                futures_balance = client.futures_account_balance()

                # Проверить условие и выполнить перевод
                if float(spot_balance['free']) < 11:
                    transfer_amount = 11 - float(spot_balance['free'])
                    # Перевести с фьючерсного на спотовый
                    client.universal_transfer(type='UMFUTURE_MAIN', asset='USDT', amount=transfer_amount)
                elif float(spot_balance['free']) > 11:
                    transfer_amount = float(spot_balance['free']) - 11
                    # Перевести со спотового на фьючерсный
                    client.universal_transfer(type='MAIN_UMFUTURE', asset='USDT', amount=transfer_amount)

                i = 0

                while not check_spot_availability(first_coin['pair']):
                    i += 1
                    first_coin = best_funding[i]
                print(first_coin['pair'], first_coin['rate'], first_coin['next_funding_time'])
                
                precision = get_precision(first_coin['pair'])
                trade_volume = round(get_trade_volume(first_coin['pair']), precision)
                client.futures_change_leverage(symbol=first_coin['pair'], leverage=1)
                sell_market = client.futures_create_order(symbol=first_coin['pair'], side='SELL', type='MARKET', positionSide='SHORT', quantity=trade_volume, leverage=1)
                order = client.order_market_buy(symbol=first_coin['pair'], quantity=trade_volume)
            else:
                time.sleep(1800)   
        else:
            time.sleep(1800)
    else:
        time.sleep(1800)