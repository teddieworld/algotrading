# algotrading
This is my journey starting algorithmic trading through programming trading strategies There will be three stages:
  - Backtesting using historical market data to evaluate the strategy's performance historically and collecting statistical data to determine the best variation and strategy to implement to live markets.
  - Once the most statistically successful strategy has been found, implement the strategy into live running markets through paper trading with (fake money) and collect data on those results for further evaluation of the strategy's success
  - After paper trading results are deemed profitable and successful, begin using real money to trade live markets

Research Question: How can I implement a trading strategy to produce a statistically significant edge in trading live markets (NASDAQ and S&P 500)?

Strategy: The strategy I have chosen to implement is the "15M ORB Strategy". In it's simplest form, we wait for the 15M candle of the New York session open (9:30 AM EST) on NASDAQ or S&P 500 Futures and use the high and low of that candle as our range. Once a 5M candle closes above or below that range, a trade is taken.

Stage 1: Backtest against historical data
  The statistics will be taken trading only 1 contract on MNQ futures, which has a signficant impact on %Increase as the futures are highly leveraged.
  
  I'll be collecting data such as 
  
    - Total trades
    - Win rate
    - Average win/loss
    - Total % Increase
    - Expectancy
    - Average R
    - Profit factor
    - Maximum drawdown
    - Number of trades per year
    - Shapre Ratio
  to make adjustments to the strategy that produces the best results
  These experiments and statistics will be tracked in the **researchlog** and the **experimentlog** which helped me in the development and research process.
  
Stage 2: Implement into paper trading:

After I am satisfied with the amount of experimenting and feel I have improved the strategy to the best it can be, I will utilize Tradovate/NinjaTrader REST API to begin implementing the strategy into their live simulated trading to see how the strategy actually performs in live markets.

  
AI USE: AI is used as a tool for me for the following purpose:
 - Guidance for code logic after I've tried to figure it out but couldn't
 - Restructuring large datasets to be compatible for my code
 - Advising me on how to make my project stand out such as the creation of a github, research log, experiment log, etc.
