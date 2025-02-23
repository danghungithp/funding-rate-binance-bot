# funding-rate-binance-bot
Automated Binance Arbitrage Script

This script implements an automated arbitrage strategy on the Binance exchange by leveraging the differences in funding rates between various trading pairs. The main idea is as follows:

## Overview

- **Selecting Trading Pairs:**  
  The script fetches funding rate data for futures contracts from Binance and selects the top 10 pairs with a positive funding rate. For each pair, it calculates an adjusted rate (taking into account the funding interval).

- **Spot Market Availability Check:**  
  From the list of selected pairs, the script picks the first one that is available for trading on the spot market.

- **Opening Positions:**  
  If there are no open positions for the selected pair and the funding rate exceeds a predefined threshold (e.g., 1%), the script opens a position by:
  - Executing a market buy on the spot market.
  - Simultaneously placing a market sell order (short position) on the futures market with minimal leverage.

- **Switching Positions:**  
  When the next funding time arrives, the script updates the list of top pairs. If a pair with a better funding rate is found (while also checking additional threshold conditions), it:
  - Closes the current positions on both the futures and spot markets.
  - Balances funds between accounts (spot and futures) to a specified level (e.g., 11 USDT).
  - Opens a new position based on the new pair.

- **Internet Connection Check:**  
  Before performing key operations, the script verifies that an internet connection is available.

- **Continuous Execution:**  
  The script runs in an infinite loop, performing checks every 30 minutes (or when conditions are met) to either maintain or switch positions as needed.

## Requirements and Setup

- **Dependencies:**
  - [python-binance](https://github.com/sammchardy/python-binance)
  - requests
  - datetime, time, math

- **Configuration:**  
  Create a file named `config.py` with your Binance API keys:
  ```python
  api_key = 'YOUR_BINANCE_API_KEY'
  api_secret = 'YOUR_BINANCE_API_SECRET'
