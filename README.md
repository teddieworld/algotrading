# algotrading
This is my journey starting algorithmic trading through programming trading strategies There will be three stages:
  - Backtesting using historical market data to evaluate the strategy's performance historically and collecting statistical data to determine the best variation and strategy to implement to live markets.
  - Once the most statistically successful strategy has been found, implement the strategy into live running markets through paper trading with (fake money) and collect data on those results for further evaluation of the strategy's success
  - After paper trading results are deemed profitable and successful, begin using real money to trade live markets

Research Question: Can I implement a trading strategy to produce a statistically significant edge in trading live markets (NASDAQ and S&P 500)?

Strategy: The strategy I have chosen to implement is the "5M ORB Strategy". In it's simplest form, we wait for the first 5M or 15M candle of the New York session open (9:30 AM EST) and use the high and low of that candle as our range. Once a 5M candle closes above or below that range, a trade is taken.

I'll be collecting data such as 
  - Total trades
  - Win rate
  - Average win/loss
  - Expectancy
  - Average R
  - Profit factor
  - Sharpe ratio
  - Maximum drawdown
  - Time in trade
  - Annual/monthly returns
  - Number of trades per year
  - Long vs short performance
to make adjustments to the strategy that produces the best results

In the future: looking to add more advanced statistical data
