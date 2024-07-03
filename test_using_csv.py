import pandas as pd
import matplotlib.pyplot as plt
import ta
from ta import trend, momentum, volatility
import numpy as np
import ta.momentum
import ta.trend
import ta.volatility

def fetch_historical_data_from_csv(symbol, start_date='2021-01-01'):
    file_path = f'historical_data_{symbol}.csv'
    data = pd.read_csv(file_path, index_col='date', parse_dates=True)
    data = data[start_date:]
    data.rename(columns={
        '1. open': 'open',
        '2. high': 'high',
        '3. low': 'low',
        '4. close': 'close',
        '5. volume': 'volume'
    }, inplace=True)
    data['price'] = data['close']
    return data

class Backtester:
    max_precisions = {
        'BTC': 8, 'ETH': 8, 'LTC': 8, 'BCH': 8, 'ADA': 6,
        'LINK': 2, 'DOT': 6, 'DOGE': 6, 'UNI': 6, 'SOL': 6,
        'SHIB': 8, 'AAVE': 8, 'ALGO': 6, 'ATOM': 6, 'FIL': 6,
        'XTZ': 6
    }

    def __init__(self, initial_balance, take_profit_threshold=0.5):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions = {}
        self.history = []
        self.max_portfolio_value = initial_balance
        self.take_profit_threshold = take_profit_threshold
        print(f"Initialized Backtester with balance: {self.cash}")

    def apply_technical_indicators(self, df):
        df['SMA'] = ta.trend.SMAIndicator(df['price'], window=20).sma_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(df['price'], window=14).rsi()
        macd = ta.trend.MACD(df['price'].fillna(0))
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['MACD_Diff'] = macd.macd_diff()
        bollinger = ta.volatility.BollingerBands(df['price'], window=20, window_dev=2)
        df['Bollinger_High'] = bollinger.bollinger_hband()
        df['Bollinger_Low'] = bollinger.bollinger_lband()
        return df

    def calculate_performance_score(self, row):
        score = 0
        if row['RSI'] < 30:
            score += 1
        elif row['RSI'] > 70:
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

    def determine_trade_amount(self, performance_score, balance, product_id, max_precision=8, portion=0.3):
        allocated_balance = balance * portion
        trade_amount = allocated_balance * performance_score / balance
        base_currency = product_id.split('-')[0]
        max_precision = self.max_precisions.get(base_currency, 6)
        trade_amount = round(trade_amount, max_precision)
        return trade_amount

    def simulate_trade(self, product_id, price, decision, trade_amount, trade_time):
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
            'time': trade_time,
            'product_id': product_id,
            'price': price,
            'decision': decision,
            'trade_amount': trade_amount,
            'cash': self.cash,
            'positions': self.positions.copy()
        })
        print("Trade executed: ", self.history[-1])

    def calculate_portfolio_value(self, price):
        positions_value = sum([amount * price for amount in self.positions.values()])
        return self.cash + positions_value

    def backtest(self, df, product_id):
        df = self.apply_technical_indicators(df)
        if len(df) < 26:
            return self.history

        for index, row in df.iloc[26:].iterrows():
            performance_score = self.calculate_performance_score(row)
            trade_amount = self.determine_trade_amount(performance_score, self.cash, product_id)
            current_portfolio_value = self.calculate_portfolio_value(row['price'])
            print("current_portfolio_value: ", current_portfolio_value)

            # Update max portfolio value
            if current_portfolio_value > self.max_portfolio_value:
                self.max_portfolio_value = current_portfolio_value

            # Check take profit condition
            if current_portfolio_value < self.max_portfolio_value * (1 - self.take_profit_threshold):
                for product in list(self.positions.keys()):
                    self.simulate_trade(product, row['price'], 'sell', self.positions[product], index)

            if trade_amount > 0:
                if performance_score > 0.5:
                    self.simulate_trade(product_id, row['price'], 'buy', trade_amount, index)
                elif performance_score < 0.5 and product_id in self.positions:
                    self.simulate_trade(product_id, row['price'], 'sell', trade_amount, index)

        return self.history

# Example usage
available_wallets = ['BTC']
historical_data = {product_id: fetch_historical_data_from_csv(product_id) for product_id in available_wallets}

backtester = Backtester(initial_balance=50000, take_profit_threshold=0.1)
backtest_results = {}
for product_id, df in historical_data.items():
    history = backtester.backtest(df, product_id)
    backtest_results[product_id] = history

# Aggregate results and plot
all_histories = [item for sublist in backtest_results.values() for item in sublist]
history_df = pd.DataFrame(all_histories)

if 'cash' not in history_df.columns:
    raise KeyError("'cash' column not found in history DataFrame.")

history_df['portfolio_value'] = history_df.apply(lambda row: sum([amount * row['price'] for amount in row['positions'].values()]) + row['cash'], axis=1)

total_return = (history_df['portfolio_value'].iloc[-1] - history_df['portfolio_value'].iloc[0]) / history_df['portfolio_value'].iloc[0] * 100
max_drawdown = (history_df['portfolio_value'].max() - history_df['portfolio_value'].min()) / history_df['portfolio_value'].max() * 100

daily_returns = history_df['portfolio_value'].pct_change().dropna()
mean_daily_return = daily_returns.mean()
std_daily_return = daily_returns.std()

sharpe_ratio = (mean_daily_return / std_daily_return) * np.sqrt(252) if std_daily_return != 0 else 0

print(f"Total Return: {total_return:.2f}%")
print(f"Max Drawdown: {max_drawdown:.2f}%")
print(f"Sharpe Ratio: {sharpe_ratio:.2f}")

history_df.plot(x='time', y='portfolio_value', title='Portfolio Value Over Time')
plt.show()