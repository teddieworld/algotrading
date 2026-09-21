import clr
import time
from datetime import datetime
import pandas as pd
import System

clr.AddReference(r"C:\Program Files\NinjaTrader 8\bin\NinjaTrader.Client.dll") #load ninjatrader client
from NinjaTrader.Client import Client

client = Client() #create a Client object


result = client.SetUp("127.0.0.1", 36973) #connect to NinjaTrader
print("SetUp result:", result)
print("Connected:", client.Connected(0))

subscribeResult = client.SubscribeMarketData("MNQ DEC26") #start getting market data
print("Subscribe result:", subscribeResult)

time.sleep(2)

#Strategy parameters
TP_Ratio = 2
contract_size = 1
SLdivider = 650
trade_open = False

#Candle data points
bar_start = None
open_price = None
high_price = None
low_price = None
close_price = None
candle_volume = None
starting_volume = None
candles = pd.DataFrame(columns = ["Date", "Open", "High", "Low", "Close", "Volume"])
orbValuesSet = False
try:
    while True: #repeatedly grab market data
        last = client.MarketData("MNQ DEC26", 0)
        volume = client.MarketData("MNQ DEC26", 6)
        current_time = datetime.now()
        minute5candle = (current_time.minute // 5) * 5
        current5mperiod = current_time.replace(minute = minute5candle, second = 0, microsecond = 0)

        if (current_time.time() < pd.to_datetime("6:30").time()): #the program will only keep track of the candles that are after 6:30 AM; market open
            print("Not running yet")
            continue

        if bar_start == None: #if the first candle has yet to be set, then set each value to whatever is currently the price
            bar_start = current5mperiod
            open_price = last
            high_price = last
            low_price = last
            close_price = last
            starting_volume = volume
        elif current5mperiod!= bar_start: #when the current time changes 5m interval, then print the values and start a new candle and save the previous candle data in the dataframe 
            candle_volume = volume - starting_volume
            new_row = {
                "Date" : [bar_start],
                "Open" : [open_price],
                "High" : [high_price],
                "Low" : [low_price],
                "Close" : [close_price],
                "Volume" : [candle_volume]
            }
            new_row = pd.DataFrame(new_row)
            candles = pd.concat([
                candles,
                new_row
            ])
            print("Bar:", bar_start, "Open:", open_price, "High:", high_price, "Low:", low_price, "Close:", close_price, "Volume:", candle_volume)

            if len(candles) == 3 and orbValuesSet == False: #when the first three 5m candles (15m) are stored, set the ORB high and low
                ORB_High = candles["High"].max()
                ORB_Low = candles["Low"].min()
                ORB_Range = ORB_High - ORB_Low
                orbValuesSet = True            

             #check for breakouts
            if orbValuesSet == True and trade_open == False:
                if candles.iloc[-1]["Close"] > ORB_High:
                    #Enter long
                    entry_price = candles.iloc[-1]["Close"]
                    entry_time = candles.iloc[-1]["Date"]
                    trade_open = True
                    position = "long"
                    SL = ORB_High - ORB_Range/SLdivider
                    TP = entry_price + ((entry_price - SL) * TP_Ratio)
                elif candles.iloc[-1]["Close"] < ORB_Low:
                    #Enter short
                    entry_price = candles.iloc[-1]["Close"]
                    entry_time = candles.iloc[-1]["Date"]
                    trade_open = True
                    position = "short"
                    SL = ORB_Low + ORB_Range/SLdivider
                    TP = entry_price - ((SL - entry_price) * TP_Ratio)

            bar_start = current5mperiod
            open_price = last
            high_price = last
            low_price = last
            close_price = last
            starting_volume = volume
        else: #check if the highs and lows change
            if last > high_price:
                high_price = last
            if last < low_price:
                low_price = last
            close_price = last
        time.sleep(1)
        



except KeyboardInterrupt: #when program stops or is interrupted by input
    print("Stopping")

finally: 
    client.UnsubscribeMarketData("MNQ DEC26") 
    client.TearDown()
    #shut down connection to NinjaTrader   
