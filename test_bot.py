import pandas as pd
import matplotlib.pyplot as plt
import ta
from alpha_vantage.cryptocurrencies import CryptoCurrencies
import time

import ta.momentum
import ta.trend
import ta.volatility

# Replace 'YOUR_ALPHA_VANTAGE_API_KEY' with your actual Alpha Vantage API key
ALPHA_VANTAGE_API_KEY = 'S06BBZBX6BVRWUPL'

def fetch_historical_data_alpha_vantage(symbol, market='USD', start_date='2021-01-01'):
    cc = CryptoCurrencies(key=ALPHA_VANTAGE_API_KEY, output_format='pandas')
    data, meta_data = cc.get_digital_currency_daily(symbol=symbol, market=market)
    
    # Print columns to debug
    print(f"Columns before renaming for {symbol}: {data.columns}")
    
    # Convert index to datetime and sort it
    data.index = pd.to_datetime(data.index)
    data = data.sort_index()

    # Filter data from the start date
    data = data[start_date:]

    # Rename columns for easier handling
    data.rename(columns={
        '1. open': 'open',
        '2. high': 'high',
        '3. low': 'low',
        '4. close': 'close',
        '5. volume': 'volume'
    }, inplace=True)

    # Print columns after renaming to debug
    print(f"Columns after renaming for {symbol}: {data.columns}")

    # Add a 'price' column for the close prices
    data['price'] = data['close']

    return data

# Example usage
available_wallets = ['BTC']
                    #, 'ETH', 'LTC', 'BCH','ADA',
                    #'LINK','DOT','DOGE','UNI','SOL',
                    #'SHIB','AAVE','ALGO','ATOM','FIL',
                    #'XTZ']
historical_data = {product_id: fetch_historical_data_alpha_vantage(product_id) for product_id in available_wallets}

class Backtester:
    max_precisions = {
        'BTC': 8,'ETH': 8,'LTC': 8,'BCH': 8,'ADA': 6,
        'LINK': 2,'DOT': 6,'DOGE': 6,'UNI': 6,'SOL': 6,
        'SHIB': 8,'AAVE': 8,'ALGO': 6,'ATOM': 6,'FIL': 6,
        'XTZ': 6
    }
    
    def __init__(self, initial_balance):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions = {}
        self.history = []

    def apply_technical_indicators(self, df):
        df['SMA'] = ta.trend.SMAIndicator(df['price'], window=20).sma_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(df['price'], window=14).rsi()
        macd = ta.trend.MACD(df['price'])
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['MACD_Diff'] = macd.macd_diff()
        bollinger = ta.volatility.BollingerBands(df['price'], window=20, window_dev=2)
        df['Bollinger_High'] = bollinger.bollinger_hband()
        df['Bollinger_Low'] = bollinger.bollinger_lband()
        return df

    def calculate_performance_score(self, row):
        score = 0
        if row['RSI'] < 40:
            score += 1
        elif row['RSI'] > 60:
            score -= 1
        if row['MACD_Diff'] > 0:
            score += 1
        elif row['MACD_Diff'] < 0:
            score -= 1
        if row['price'] < row['Bollinger_Low']:
            score += 1
        elif row['price'] > row['Bollinger_High']:
            score -= 1
        if row['price'] > row['SMA']:
            score += 1
        elif row['price'] < row['SMA']:
            score -= 1
        normalized_score = (score + 4) / 8
        return normalized_score

    def determine_trade_amount(self, performance_score, balance, product_id, portion=0.1):
        allocated_balance = balance * portion
        trade_amount = allocated_balance * performance_score
        base_currency = product_id.split('-')[0]
        max_precision = self.max_precisions.get(base_currency, 6)  # Default to 6 if not found
        trade_amount = round(trade_amount, max_precision)
        return trade_amount

    def simulate_trade(self, product_id, price, decision, trade_amount):
        if decision == 'buy' and self.cash >= trade_amount * price:
            self.cash -= trade_amount * price
            if product_id not in self.positions:
                self.positions[product_id] = 0
            self.positions[product_id] += trade_amount
        elif decision == 'sell' and product_id in self.positions and self.positions[product_id] >= trade_amount:
            self.cash += trade_amount * price
            self.positions[product_id] -= trade_amount
            if self.positions[product_id] == 0:
                del self.positions[product_id]
        self.history.append({
            'time': pd.Timestamp.now(),
            'product_id': product_id,
            'price': price,
            'decision': decision,
            'trade_amount': trade_amount,
            'cash': self.cash,
            'positions': self.positions.copy()
        })

    def backtest(self, df, product_id):
        df = self.apply_technical_indicators(df)
        for index, row in df.iterrows():
            if df.index.get_loc(index) < 26:  # Ensure enough data for indicators
                continue
            performance_score = self.calculate_performance_score(row)
            trade_amount = self.determine_trade_amount(performance_score, self.cash, product_id)
            if trade_amount > 0:
                if performance_score > 0.5:
                    self.simulate_trade(product_id, row['price'], 'buy', trade_amount)
                elif performance_score < 0.5:
                    self.simulate_trade(product_id, row['price'], 'sell', trade_amount)
        return self.history

def evaluate_performance(all_histories):
    history_df = pd.DataFrame(all_histories)
    if history_df.empty:
        print("No trades were made during the backtest period.")
        return

    history_df['portfolio_value'] = history_df['cash'] + history_df['positions'].apply(
        lambda pos: sum(pos[product_id] * historical_data[product_id]['price'].iloc[-1] for product_id in pos)
    )
    total_return = (history_df['portfolio_value'].iloc[-1] / backtester.initial_balance) - 1
    max_drawdown = (history_df['portfolio_value'].max() - history_df['portfolio_value'].min()) / history_df['portfolio_value'].max()
    returns = history_df['portfolio_value'].pct_change().dropna()
    if returns.std() != 0:
        sharpe_ratio = (returns.mean() / returns.std()) * (252**0.5)
    else:
        sharpe_ratio = float('nan')  # Avoid division by zero

    print(f"Total Return: {total_return * 100:.2f}%")
    print(f"Max Drawdown: {max_drawdown * 100:.2f}%")
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")

    plt.plot(history_df['time'], history_df['portfolio_value'])
    plt.title("Portfolio Value Over Time")
    plt.xlabel("Time")
    plt.ylabel("Portfolio Value")
    plt.show()

# Example usage for multiple cryptocurrencies
backtester = Backtester(initial_balance=50000)
backtest_results = {}
for product_id, df in historical_data.items():
    history = backtester.backtest(df, product_id)
    backtest_results[product_id] = history

# Aggregate results
all_histories = [item for sublist in backtest_results.values() for item in sublist]

evaluate_performance(all_histories)