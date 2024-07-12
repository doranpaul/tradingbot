import os
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
import ta.volatility
import uuid
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

api_key = os.getenv("api_key")
api_secret = os.getenv("api_secret")

client = RESTClient(api_key=api_key, api_secret=api_secret)

available_wallets = [
    'BTC-GBP', 'ETH-GBP', 'LTC-GBP', 'BCH-GBP',
    'ADA-GBP', 'LINK-GBP', 'DOT-GBP', 'DOGE-GBP',
    'UNI-GBP', 'SOL-GBP', 'SHIB-GBP', 'AAVE-GBP', 'ALGO-GBP',
    'ATOM-GBP', 'FIL-GBP', 'XTZ-GBP'
]

# Dictionary to hold real-time data
real_time_data = {wallet: pd.DataFrame(columns=['time', 'price']) for wallet in available_wallets}
trade_counters = {wallet: 0 for wallet in available_wallets}

# Generate a unique session identifier
session_id = str(uuid.uuid4())

# Record entry prices for positions
entry_prices = {wallet: None for wallet in available_wallets}

# Stop-loss and take-profit thresholds
STOP_LOSS_PERCENTAGE = 0.05  # 5%
TAKE_PROFIT_PERCENTAGE = 0.1  # 10%

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

# Function to apply technical indicators
def apply_technical_indicators(df):
    try:
        if len(df) < 20:
            print("Not enough data to apply technical indicators")
            return df
        
        df['SMA'] = ta.trend.SMAIndicator(df['price'], window=20).sma_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(df['price'], window=14).rsi()
        
        if len(df) >= 26:  # Ensure there is enough data for MACD
            macd = ta.trend.MACD(df['price'])
            df['MACD'] = macd.macd()
            df['MACD_Signal'] = macd.macd_signal()
            df['MACD_Diff'] = macd.macd_diff()
        else:
            df['MACD'] = float('nan')
            df['MACD_Signal'] = float('nan')
            df['MACD_Diff'] = float('nan')
        
        bollinger = ta.volatility.BollingerBands(df['price'], window=20, window_dev=2)
        df['Bollinger_High'] = bollinger.bollinger_hband()
        df['Bollinger_Low'] = bollinger.bollinger_lband()
        
        #print("Applied technical indicators: SMA, RSI, MACD, Bollinger Bands")
        return df
    except Exception as e:
        print(f"Error applying indicators: {e}")
        return df

def calculate_performance_score(df):
    if df.empty or len(df) < 26:
        print(f"Not enough data to calculate performance score.")
        return 0

    latest_data = df.iloc[-1]
    score = 0

    # RSI signal
    if latest_data['RSI'] < 30:
        score += 1
    elif latest_data['RSI'] > 70:
        score -= 1

    # MACD signal
    if latest_data['MACD_Diff'] > 0:
        score += 1
    elif latest_data['MACD_Diff'] < 0:
        score -= 1

    # Bollinger Bands signal
    if latest_data['price'] < latest_data['Bollinger_Low']:
        score += 1
    elif latest_data['price'] > latest_data['Bollinger_High']:
        score -= 1

    # SMA signal
    if latest_data['price'] > latest_data['SMA']:
        score += 1
    elif latest_data['price'] < latest_data['SMA']:
        score -= 1

    # Additional indicators
    if 'ATR' in df.columns and latest_data['ATR'] < latest_data['ATR'].mean():
        score += 0.5
    if 'OBV' in df.columns and latest_data['OBV'] > latest_data['OBV'].mean():
        score += 0.5

    normalized_score = (score + 4) / 8
    print(f"Calculated performance score: {normalized_score} for data: {latest_data}")
    return normalized_score

buy_max_precisions = {
    'BTC': 2,'ETH': 2,'LTC': 2,'BCH': 2,'ADA': 2,
    'LINK': 2,'DOT': 2,'DOGE': 2,'UNI': 2,'SOL': 2,
    'SHIB': 2,'AAVE': 2,'ALGO': 2,'ATOM': 2,'FIL': 2,
    'XTZ': 2
}

sell_max_precisions = {
    'BTC': 4,'ETH': 6,'LTC': 2,'BCH': 2,'ADA': 6,
    'LINK': 1,'DOT': 1,'DOGE': 6,'UNI': 1,'SOL': 3,
    'SHIB': 6,'AAVE': 2,'ALGO': 6,'ATOM': 6,'FIL': 1,
    'XTZ': 6
}

def determine_buy_trade_amount(performance_score, gbp_balance, product_id, portion=0.3):
    allocated_balance = gbp_balance * portion
    trade_amount = allocated_balance * performance_score
    
    base_currency = product_id.split('-')[0]
    max_precision = buy_max_precisions.get(base_currency, 6)
    min_trade_amount = min_trade_amounts.get(base_currency, 0.0001)
    
    trade_amount = round(trade_amount, max_precision)
    if trade_amount < 1:
        trade_amount = 1  # Ensure trade amount respects the minimum
    
    # Ensure trade amount is not zero
    if trade_amount == 0:
        trade_amount = min_trade_amount
    
    print(f"Determined buy trade amount for {product_id}: {trade_amount:.{max_precision}f} for performance score: {performance_score:.2f} and GBP balance: {gbp_balance:.8f}")
    return trade_amount


def determine_sell_trade_amount(performance_score, coin_balance, product_id, portion=0.3):
    allocated_balance = coin_balance * portion
    trade_amount = allocated_balance * performance_score
    
    base_currency = product_id.split('-')[0]
    max_precision = sell_max_precisions.get(base_currency, 6)
    min_trade_amount = min_trade_amounts.get(base_currency, 0.0001)
    
    trade_amount = round(trade_amount, max_precision)
    if trade_amount < min_trade_amount:
        trade_amount = min_trade_amount  # Ensure trade amount respects the minimum
    
    print(f"Determined sell trade amount for {product_id}: {trade_amount:.{max_precision}f} for performance score: {performance_score:.2f} and coin balance: {coin_balance:.8f}")
    return trade_amount


# Function to execute trades
def execute_trade(decision, product_id, trade_amount):
    base_currency = product_id.split('-')[0]
    min_trade_amount = min_trade_amounts.get(base_currency, 0.0001)
    
    if trade_amount >= min_trade_amount and trade_amount > 0:
        try:
            trade_counters[product_id] += 1  # Increment the counter for each trade
            client_order_id = f"{session_id}_{product_id}_{trade_counters[product_id]}"
            
            if decision == 'buy':
                order = client.market_order_buy(client_order_id=f"order_buy_{client_order_id}", product_id=product_id, quote_size=str(trade_amount))
                print(f"Executed buy order: {order}")
                if order.get('success'):
                    entry_prices[product_id] = order['price']  # Store the entry price
            elif decision == 'sell':
                order = client.market_order_sell(client_order_id=f"order_sell_{client_order_id}", product_id=product_id, base_size=str(trade_amount))
                print(f"Executed sell order: {order}")
                if order.get('success'):
                    entry_prices[product_id] = None  # Reset the entry price
                
                if not order.get('success'):
                    print(f"Failed to execute order: {order.get('failure_reason', 'Unknown reason')}")
                else:
                    print(json.dumps(order, indent=2))
        except Exception as e:
            print(f"Error executing {decision} order for {product_id} with amount {trade_amount}: {e}")
    else:
        print(f"Trade amount {trade_amount:.8f} is too small to execute for {decision} on {product_id}")



min_trade_amounts = {
    'BTC': 0.0001,'ETH': 0.0001,'LTC': 0.01,'BCH': 0.01,'ADA': 10,
    'LINK': 0.1,'DOT': 0.1,'DOGE': 10,'UNI': 0.1,'SOL': 0.001,
    'SHIB': 1000,'AAVE': 0.01,'ALGO': 10,'ATOM': 1,'FIL': 0.1,
    'XTZ': 1
}
# Function to check account balances and make trading decisions
def check_and_trade():
    accounts = client.get_accounts()
    gbp_balance = 0
    portfolio = {}

    for account in accounts['accounts']:
        currency = account['currency']
        balance = float(account['available_balance']['value'])
        portfolio[currency] = balance
        if currency == 'GBP':
            gbp_balance = balance

    for account in accounts['accounts']:
        currency = account['currency']
        if currency != 'GBP':
            product_id = f"{currency}-GBP"
            if product_id in available_wallets:
                df = real_time_data[product_id].copy()
                if len(df) >= 26:
                    df = apply_technical_indicators(df)
                    performance_score = calculate_performance_score(df)
                    current_price = df['price'].iloc[-1]

                    if entry_prices[product_id]:
                        entry_price = entry_prices[product_id]
                        if current_price <= entry_price * (1 - STOP_LOSS_PERCENTAGE):
                            print(f"Stop loss triggered for {product_id}: current price {current_price} <= entry price {entry_price} * (1 - {STOP_LOSS_PERCENTAGE})")
                            coin_balance = portfolio[currency]
                            trade_amount = determine_sell_trade_amount(performance_score, coin_balance, product_id)
                            if trade_amount >= min_trade_amounts.get(currency, 0.0001):
                                execute_trade('sell', product_id, trade_amount)
                            else:
                                print(f"Trade amount {trade_amount:.8f} is below the minimum trade amount for {currency} on {product_id} (stop-loss triggered)")
                        elif current_price >= entry_price * (1 + TAKE_PROFIT_PERCENTAGE):
                            print(f"Take profit triggered for {product_id}: current price {current_price} >= entry price {entry_price} * (1 + {TAKE_PROFIT_PERCENTAGE})")
                            coin_balance = portfolio[currency]
                            trade_amount = determine_sell_trade_amount(performance_score, coin_balance, product_id)
                            if trade_amount >= min_trade_amounts.get(currency, 0.0001):
                                execute_trade('sell', product_id, trade_amount)
                            else:
                                print(f"Trade amount {trade_amount:.8f} is below the minimum trade amount for {currency} on {product_id} (take-profit triggered)")

                    if performance_score > 0.5:
                        trade_amount = determine_buy_trade_amount(performance_score, gbp_balance, product_id)
                        if trade_amount >= min_trade_amounts.get(currency, 0.0001) and trade_amount > 0:
                            execute_trade('buy', product_id, trade_amount)
                        else:
                            print(f"Trade amount {trade_amount:.8f} is below the minimum trade amount for {currency} on {product_id}")
                    elif performance_score < 0.5:
                        coin_balance = portfolio[currency]
                        trade_amount = determine_sell_trade_amount(performance_score, coin_balance, product_id)
                        if trade_amount >= min_trade_amounts.get(currency, 0.0001) and trade_amount > 0:
                            execute_trade('sell', product_id, trade_amount)
                        else:
                            print(f"Trade amount {trade_amount:.8f} is below the minimum trade amount for {currency} on {product_id}")
                    else:
                        print(f"Performance score is neutral: {performance_score:.2f} for {product_id}")
    if gbp_balance == 0:
        print("GBP balance is zero. Cannot execute trades.")


# Retry mechanism for WebSocket connection
async def run_websocket(duration, retries=5, retry_delay=5):
    for attempt in range(retries):
        try:
            ws_client = WSClient(api_key, api_secret, on_message=on_message)
            ws_client.open()
            ws_client.subscribe(product_ids=available_wallets, channels=["ticker", "heartbeat"])
            await asyncio.sleep(duration)
            ws_client.close()
            break
        except Exception as e:
            print(f"WebSocket connection failed: {e}. Attempt {attempt + 1}/{retries}")
            await asyncio.sleep(retry_delay)

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
        print_wallet_balances()
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