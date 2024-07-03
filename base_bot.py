import threading
from coinbase.rest import RESTClient
import time
import pandas as pd
import ta
import asyncio
from coinbase.websocket import WSClient
import json
from json import dumps, loads
import signal

import ta.momentum
import ta.trend

api_key = "organizations/c205ec34-4a85-4111-bdd4-23aaf14c8e25/apiKeys/3b7fc225-615e-4801-86a7-2aa954a24c26"
api_secret = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIMDJv4di7KoaICisgBN976RJD7FYFZXTUB3/3/uRD0zEoAoGCCqGSM49\nAwEHoUQDQgAEQ8Zc5da/GV9opTDXJ5p2j4oEXBZCkHlbs79N9bJAQPIdO1scr6t4\n6BiVxuT88eFWQTt1DGfbOSrmm3S2W1TEsQ==\n-----END EC PRIVATE KEY-----\n"

client = RESTClient(api_key=api_key, api_secret=api_secret)

#accounts = client.get_accounts()
#print(dumps(accounts, indent=2))
#market_data = client.get_candles(product_id="BTC-GBP")

#order = client.market_order_buy(client_order_id="testPurchase", product_id="BTC-GBP", quote_size="1")
#print(dumps(order, indent=2))
#print(client.get_portfolios())
#print(client.get_portfolio_breakdown())

available_wallets = [
    'BTC-GBP', 'ETH-GBP', 'LTC-GBP', 'BCH-GBP',
    'ADA-GBP', 'LINK-GBP', 'DOT-GBP', 'DOGE-GBP',
    'UNI-GBP', 'SOL-GBP', 'SHIB-GBP', 'AAVE-GBP', 'ALGO-GBP',
    'ATOM-GBP', 'FIL-GBP', 'XTZ-GBP'
]

# Dictionary to hold real-time data
real_time_data = {wallet: pd.DataFrame(columns=['time', 'price']) for wallet in available_wallets}

# Function to print balances of each wallet
def print_wallet_balances():
    accounts = client.get_accounts()
    print("Current Wallet Balances:")
    for account in accounts['accounts']:
        currency = account['currency']
        balance = float(account['available_balance']['value'])
        print(f"{currency} Wallet: {balance} {currency}")

# Define the callback function for WebSocket messages
def on_message(msg):
    data = json.loads(msg)
    if 'events' in data:
        for event in data['events']:
            for ticker in event.get('tickers', []):
                product_id = ticker.get('product_id')
                if product_id in available_wallets:
                    time_str = ticker.get('time') or data.get('timestamp')
                    if not time_str:
                        print(f"Skipping ticker without time: {ticker}")
                        continue
                    
                    timestamp = pd.to_datetime(time_str)
                    price = float(ticker.get('price', 0))
                    new_row = pd.DataFrame({'time': [timestamp], 'price': [price]})
                    if not real_time_data[product_id].empty:
                        real_time_data[product_id] = pd.concat([real_time_data[product_id], new_row], ignore_index=True)
                    else:
                        real_time_data[product_id] = new_row
                    #print(f"Appended data for {product_id}: {new_row}")
                    #print(f"Updated DataFrame for {product_id}: {real_time_data[product_id].tail()}")

# Function to apply technical indicators
def apply_indicators(df):
    try:
        df['rsi'] = ta.momentum.RSIIndicator(df['price'], window=14).rsi()  # Ensure window is set correctly
        macd = ta.trend.MACD(df['price'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_diff'] = macd.macd_diff()
        return df
    except Exception as e:
        print(f"Error applying indicators: {e}")
        return df

# Function to calculate performance score
def calculate_performance_score(df):
    if df.empty or len(df) < 26:  # Ensure minimum number of data points
        print("Not enough data to calculate performance score.")
        return 0
    latest_data = df.iloc[-1]
    score = 0
    if latest_data['rsi'] < 30:
        score += 1
    if latest_data['macd_diff'] > 0:
        score += 1
    print(f"Calculated performance score: {score} for data: {latest_data}")
    return score

# Function to determine trade amount
def determine_trade_amount(performance_score, balance, portion=0.1):
    allocated_balance = balance * portion
    trade_amount = allocated_balance * (performance_score / 2)  # Example logic
    print(f"Determined trade amount: {trade_amount} for performance score: {performance_score} and balance: {balance}")
    return trade_amount

# Function to execute trades
def execute_trade(decision, product_id, trade_amount):
    if trade_amount > 0:  # Ensure we are only making valid trades
        if decision == 'buy':
            order = client.market_order_buy(client_order_id="order123", product_id=product_id, quote_size=str(trade_amount))
            print(f"Executed buy order: {order}")
        elif decision == 'sell':
            order = client.market_order_sell(client_order_id="order123", product_id=product_id, base_size=str(trade_amount))
            print(f"Executed sell order: {order}")
    else:
        print(f"No valid trade amount: {trade_amount} for {decision} on {product_id}")

# Function to check account balances and make trading decisions
def check_and_trade():
    accounts = client.get_accounts()
    gbp_balance = 0
    for account in accounts['accounts']:
        currency = account['currency']
        balance = float(account['available_balance']['value'])
        if currency == 'GBP':
            gbp_balance = balance

    for account in accounts['accounts']:
        currency = account['currency']
        if currency != 'GBP':
            product_id = f"{currency}-GBP"
            if product_id in available_wallets:
                df = real_time_data[product_id].copy()
                print(f"Data for {product_id}: {df.tail()}")  # Debugging: show the last few rows of data
                if len(df) >= 26:  # Ensure we have enough data points for MACD and RSI
                    df = apply_indicators(df)
                    performance_score = calculate_performance_score(df)
                    if performance_score > 0:  # Ensure there is a valid performance score
                        trade_amount = determine_trade_amount(performance_score, balance)  # Use balance of the specific coin

                        if trade_amount > 0:
                            if performance_score > 1:  # Example decision logic
                                execute_trade('buy', product_id, trade_amount)
                            elif performance_score < 1:
                                execute_trade('sell', product_id, trade_amount)
                        else:
                            print(f"No valid trade amount: {trade_amount} for {currency} on {product_id}")
    if gbp_balance == 0:
        print("GBP balance is zero. Cannot execute trades.")

# Run the WebSocket in an asynchronous loop
async def run_websocket(duration):
    ws_client = WSClient(api_key, api_secret, on_message=on_message)
    ws_client.open()
    ws_client.subscribe(product_ids=available_wallets, channels=["ticker", "heartbeat"])
    await asyncio.sleep(duration)  # Run WebSocket for the specified duration
    ws_client.close()

# Event to signal stopping the bot
stop_event = threading.Event()

# Graceful shutdown handler
def shutdown_handler(signum, frame):
    print("Shutting down...")
    stop_event.set()

# Register the signal handlers
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# Main function to run the data collection and trading logic in cycles
async def main():
    print_wallet_balances()  # Print wallet balances at the beginning
    while not stop_event.is_set():
        print("Collecting data...")
        await run_websocket(60)  # Run WebSocket for 1 minute to collect data
        print("Running trading logic...")
        check_and_trade()
        print("Sleeping for 5 minutes...")
        await asyncio.sleep(300)  # Sleep for 5 minutes before collecting data again

# Start the main asynchronous loop
def run_main():
    asyncio.run(main())

# Run the main function in a separate thread to handle signals
main_thread = threading.Thread(target=run_main)
main_thread.start()

# Wait for the main thread to finish
main_thread.join()