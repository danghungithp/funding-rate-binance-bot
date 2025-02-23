from config import api_key, api_secret
from binance.client import Client
import requests
import datetime
import time
import math

# Initialize Binance client using API keys
client = Client(api_key, api_secret)

# Defined deposit in USDT used for calculating trade volume
deposit = 9.9  # Deposit in USDT

first_iteration = True  # Flag to indicate the first trading iteration
i = 0  # Index for selecting a pair from the top funding pairs list

def check_internet():
    """
    Checks for an active internet connection by sending a request to Google.
    Returns True if the connection is successful, False otherwise.
    """
    url = "http://www.google.com"
    timeout = 5  # Timeout in seconds
    try:
        _ = requests.get(url, timeout=timeout)
        return True
    except requests.ConnectionError:
        print("No internet connection.")
        return False

def check_spot_availability(symbol):
    """
    Checks whether the given trading pair is available on the spot market.
    It fetches all tickers and searches for the specified pair.
    Returns True if the pair is found, otherwise False.
    """
    tickers = client.get_all_tickers()
    for ticker in tickers:
        if ticker['symbol'] == symbol:
            return True
    return False

def get_current_price(symbol):
    """
    Retrieves the current (last) price for the given trading pair.
    """
    ticker = client.get_ticker(symbol=symbol)
    current_price = float(ticker['lastPrice'])
    return current_price

def get_trade_volume(pair):
    """
    Calculates the trading volume based on the deposit.
    It divides the deposit by the current price of the pair and rounds the result
    according to the required precision.
    """
    # Get the volume precision for the trading pair (using the global variable first_coin)
    precision = get_precision(first_coin['pair'])
    # Calculate volume: deposit / current price, rounded to the correct number of decimals
    volume = round(deposit / get_current_price(pair), precision)
    print(f"Trade volume: {volume}")
    return volume

def close_future_position(client: Client, symbol: str):
    """
    Closes an open futures position for the given trading pair.
    - Retrieves information on all open positions.
    - If a non-zero position is found, determines the side (buy or sell) to close it.
    - Creates a market order to close the position.
    Returns the order information or None if no positions are open.
    """
    open_positions = client.futures_position_information(symbol=symbol)
    for position in open_positions:
        if float(position['positionAmt']) != 0:
            quantity = abs(float(position['positionAmt']))
            # If the position is long (positive amount), close it with a sell order;
            # if short (negative amount), use a buy order.
            side = Client.SIDE_SELL if float(position['positionAmt']) > 0 else Client.SIDE_BUY

            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type=Client.ORDER_TYPE_MARKET,
                quantity=quantity,
                # Define the position: "BOTH" for a sell order and "SHORT" for a buy order.
                positionSide="BOTH" if side == Client.SIDE_SELL else "SHORT"
            )
            return order
    return None

def close_spot_position(symbol):
    """
    Closes the spot position for the given pair by selling all available assets.
    - Determines the asset from the pair symbol.
    - Retrieves the free balance of the asset.
    - Calculates the lot size and rounds the quantity to an acceptable value.
    - Sends a market sell order if the quantity is greater than zero.
    """
    asset = symbol[:-4]  # Extract asset from the symbol (e.g., 'BTCUSDT' -> 'BTC')
    free_balance = client.get_asset_balance(asset=asset)['free']

    # Retrieve symbol information including filters (like LOT_SIZE)
    info = client.get_symbol_info(symbol)
    step_size = 0.0
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            step_size = float(f['stepSize'])

    # Round the free balance to an acceptable quantity considering the step_size
    quantity = math.floor(float(free_balance) / step_size) * step_size

    if quantity > 0:
        # Place a market sell order to close the position
        client.order_market_sell(symbol=symbol, quantity=quantity)

def get_precision(symbol):
    """
    Retrieves the precision (number of decimal places) for the futures trading pair's volume.
    Iterates over the list of symbols from futures_exchange_info and returns the appropriate value.
    """
    info = client.futures_exchange_info()
    for asset in info['symbols']:
        if asset['symbol'] == symbol:
            return asset['quantityPrecision']
    return None

def get_funding_interval(symbol):
    """
    Retrieves the funding interval (in hours) for the given trading pair.
    Sends a request to the Binance API to obtain funding information.
    """
    response = requests.get(f'https://fapi.binance.com/fapi/v1/fundingInfo?symbol={symbol}')
    data = response.json()
    return data[0]['fundingIntervalHours']

def get_best_positive_funding():
    """
    Extracts information for trading pairs with a positive funding rate.
    - Requests funding rate data from Binance (premiumIndex).
    - Filters pairs with a positive funding rate.
    - Sorts them in descending order by funding rate.
    - Selects the top 10 pairs.
    - For each pair, calculates the next funding time and adjusts the rate if the funding interval is 4 hours (doubling the rate).
    Returns a list of dictionaries with keys: 'pair', 'rate', and 'next_funding_time'.
    """
    response = requests.get('https://fapi.binance.com/fapi/v1/premiumIndex')
    data = response.json()
    positive_funding = [item for item in data if float(item['lastFundingRate']) > 0]
    sorted_pairs = sorted(positive_funding, key=lambda x: float(x['lastFundingRate']), reverse=True)
    top_10_pairs = sorted_pairs[:10]
    result = []
    for pair in top_10_pairs:
        # Convert next funding time to a datetime object
        next_funding_time = datetime.datetime.fromtimestamp(int(pair['nextFundingTime']) / 1000)
        funding_interval = get_funding_interval(pair['symbol'])
        rate = float(pair['lastFundingRate']) * 100  # Convert to percentage
        if funding_interval == 4:
            rate *= 2  # Adjust rate for a 4-hour interval
        result.append({
            'pair': pair['symbol'],
            'rate': rate,
            'next_funding_time': next_funding_time
        })
    return result

def get_specific_pair_funding(symbol):
    """
    Retrieves the funding rate information for a specific trading pair.
    If the pair is found, returns a tuple (symbol, funding rate in percentage, next funding time);
    otherwise, returns None.
    """
    response = requests.get('https://fapi.binance.com/fapi/v1/premiumIndex')
    data = response.json()
    pair_data = next((item for item in data if item["symbol"] == symbol), None)
    if pair_data is not None:
        next_funding_time = datetime.datetime.fromtimestamp(int(pair_data['nextFundingTime']) / 1000)
        return pair_data['symbol'], float(pair_data['lastFundingRate']) * 100, next_funding_time
    else:
        return None

def check_open_positions(symbol):
    """
    Checks for open futures positions on the given trading pair.
    Returns True if any position with a non-zero quantity is found, otherwise False.
    """
    positions = client.futures_position_information(symbol=symbol)
    for position in positions:
        if float(position['positionAmt']) != 0:
            return True
    return False

# Retrieve the list of top pairs with a positive funding rate
best_funding = get_best_positive_funding()
first_coin = best_funding[i]

# Select the first pair that is available on the spot market
while not check_spot_availability(first_coin['pair']):
    i += 1
    first_coin = best_funding[i]

print(first_coin['pair'], first_coin['rate'], first_coin['next_funding_time'])

# Main loop of the script
while True:
    if check_internet():
        # Get the precision and calculate the trade volume
        precision = get_precision(first_coin['pair'])
        trade_volume = round(get_trade_volume(first_coin['pair']), precision)

        # If there is no open position for the current pair and the funding rate is above 1%
        if not check_open_positions(first_coin['pair']) and first_coin['rate'] > 1.0:
            if first_iteration:
                # Set leverage for the futures position
                client.futures_change_leverage(symbol=first_coin['pair'], leverage=1)
                # Open a spot market position (buy)
                order = client.order_market_buy(symbol=first_coin['pair'], quantity=trade_volume)
                # Open a futures short position (sell)
                sell_market = client.futures_create_order(
                    symbol=first_coin['pair'],
                    side='SELL',
                    type='MARKET',
                    positionSide='SHORT',
                    quantity=trade_volume,
                    leverage=1
                )
            else:
                first_iteration = False

        # If the current funding time has arrived for the selected pair
        if datetime.datetime.now() >= first_coin['next_funding_time']:
            j = 0
            # Retrieve the updated list of pairs with positive funding rates
            actually_best_funding = get_best_positive_funding()
            actually_first_coin = actually_best_funding[j]
            print(actually_first_coin['pair'], actually_first_coin['rate'], actually_first_coin['next_funding_time'])

            # Select a pair that is available on the spot market
            while not check_spot_availability(actually_first_coin['pair']):
                j += 1
                actually_first_coin = actually_best_funding[j]

            # If the new pair offers a better funding rate (and meets additional conditions),
            # close the current positions and open new positions based on the new pair.
            if (first_coin['rate'] < actually_first_coin['rate'] and
                first_coin['pair'] != actually_first_coin['pair'] and
                (first_coin['rate'] < 0.5 or actually_first_coin['rate'] > 1.0)):
                
                # Close the futures and spot positions for the current pair
                close_future_position(client, first_coin['pair'])
                close_spot_position(first_coin['pair'])
                
                # Get the spot balance (USDT)
                spot_balance = client.get_asset_balance(asset='USDT')
                # Get the futures account balance (for additional logic if needed)
                futures_balance = client.futures_account_balance()

                # Transfer funds between accounts to balance to 11 USDT
                if float(spot_balance['free']) < 11:
                    transfer_amount = 11 - float(spot_balance['free'])
                    # Transfer from futures to spot account
                    client.universal_transfer(type='UMFUTURE_MAIN', asset='USDT', amount=transfer_amount)
                elif float(spot_balance['free']) > 11:
                    transfer_amount = float(spot_balance['free']) - 11
                    # Transfer from spot to futures account
                    client.universal_transfer(type='MAIN_UMFUTURE', asset='USDT', amount=transfer_amount)

                # Reset the index for selecting a new pair
                i = 0
                while not check_spot_availability(first_coin['pair']):
                    i += 1
                    first_coin = best_funding[i]
                print(first_coin['pair'], first_coin['rate'], first_coin['next_funding_time'])
                
                # Calculate volume and set leverage for the new position
                precision = get_precision(first_coin['pair'])
                trade_volume = round(get_trade_volume(first_coin['pair']), precision)
                client.futures_change_leverage(symbol=first_coin['pair'], leverage=1)
                # Open a futures short position for the new pair
                sell_market = client.futures_create_order(
                    symbol=first_coin['pair'],
                    side='SELL',
                    type='MARKET',
                    positionSide='SHORT',
                    quantity=trade_volume,
                    leverage=1
                )
                # Open a spot market position (buy) for the new pair
                order = client.order_market_buy(symbol=first_coin['pair'], quantity=trade_volume)
            else:
                # If the conditions for switching positions are not met, wait for 30 minutes
                time.sleep(1800)   
        else:
            # If the funding time has not yet arrived, wait for 30 minutes
            time.sleep(1800)
    else:
        # If there is no internet connection, wait 30 minutes and try again
        time.sleep(1800)