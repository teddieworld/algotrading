import clr
import time
from datetime import datetime
import pandas as pd

# load ninjatrader client
clr.AddReference(r"C:\Program Files\NinjaTrader 8\bin\NinjaTrader.Client.dll")
from NinjaTrader.Client import Client

def executeTrade(position, marketOrder, stopLossOrder, takeProfitOrder, oco_Id):
    if position == "long":
        # Enter long
        entry_time = candles.iloc[-1]["Date"]
        SL = ORB_High - ORB_Range/SLdivider

        # Create order IDS for each order type

        # Execute market order
        entry_result = client.Command(
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "BUY",
            contract_size,
            "MARKET",
            0,
            0,
            "DAY",
            "",
            marketOrder,
            "",
            ""
        )
        # Wait for order to be confirmed filled
        while client.OrderStatus(marketOrder) != "Filled":
            time.sleep(0.1)
        # Once the loop ends are the order is filled, we set the entry_price and TP
        entry_price = client.AvgFillPrice(marketOrder)
        TP = entry_price + ((entry_price - SL) * TP_Ratio)
        # Execute SL
        sl_result = client.Command(
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "SELL",
            contract_size,
            "STOPMARKET",
            0,
            SL,
            "DAY",
            oco_Id,
            stopLossOrder,
            "",
            ""
        )
        # Execute TP
        tp_result = client.Command(
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "SELL",
            contract_size,
            "LIMIT",
            TP,
            0,
            "DAY",
            oco_Id,
            takeProfitOrder,
            "",
            ""
        )
        return True
    elif position == "short":
        # Enter short
        entry_time = candles.iloc[-1]["Date"]
        SL = ORB_Low + ORB_Range/SLdivider

        # Create order IDS for each order type

        # Execute market order
        entry_result = client.Command(
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "SELL",
            contract_size,
            "MARKET",
            0,
            0,
            "DAY",
            "",
            marketOrder,
            "",
            ""
        )
        # Wait for order to be confirmed filled
        while client.OrderStatus(marketOrder) != "Filled":
            time.sleep(0.1)
        # Once the loop ends are the order is filled, we set the entry_price and TP
        entry_price = client.AvgFillPrice(marketOrder)
        TP = entry_price - ((SL - entry_price) * TP_Ratio)

        # Execute SL
        sl_result = client.Command(
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "BUY",
            contract_size,
            "STOPMARKET",
            0,
            SL,
            "DAY",
            oco_Id,
            stopLossOrder,
            "",
            ""
        )
        # Execute TP
        tp_result = client.Command(
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "BUY",
            contract_size,
            "LIMIT",
            TP,
            0,
            "DAY",
            oco_Id,
            takeProfitOrder,
            "",
            ""
        )
        return True

def liquidatePositions(position, stopLossOrder, takeProfitOrder):
    if position == None:
        return
    liquidationOrder = client.NewOrderId()
    if position == "long":
        client.Command(
            "CANCEL",
            "DEMO7641540",
            "MNQ DEC26",
            "",
            0,
            "",
            0,
            0,
            "",
            "",
            stopLossOrder,
            "",
            ""
        )
        client.Command(
            "CANCEL",
            "DEMO7641540",
            "MNQ DEC26",
            "",
            0,
            "",
            0,
            0,
            "",
            "",
            takeProfitOrder,
            "",
            ""
        )
        client.Command( #cancel the long order
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "SELL",
            contract_size,
            "MARKET",
            0,
            0,
            "DAY",
            "",
            liquidationOrder,
            "",
            ""
        )
        while client.OrderStatus(liquidationOrder) != "Filled":
            time.sleep(0.1)
        print("Long order liquidated")
    elif position == "short":
        client.Command(
            "CANCEL",
            "DEMO7641540",
            "MNQ DEC26",
            "",
            0,
            "",
            0,
            0,
            "",
            "",
            stopLossOrder,
            "",
            ""
        )
        client.Command(
            "CANCEL",
            "DEMO7641540",
            "MNQ DEC26",
            "",
            0,
            "",
            0,
            0,
            "",
            "",
            takeProfitOrder,
            "",
            ""
        )  
        client.Command( #cancel the short order
            "PLACE",
            "DEMO7641540",
            "MNQ DEC26",
            "BUY",
            contract_size,
            "MARKET",
            0,
            0,
            "DAY",
            "",
            liquidationOrder,
            "",
            ""
        ) 
        while client.OrderStatus(liquidationOrder) != "Filled":
            time.sleep(0.1)
        print("Long order liquidated")


client = Client()  # create a Client object

result = client.SetUp("127.0.0.1", 36973)  # connect to NinjaTrader
print("SetUp result:", result)
print("Connected:", client.Connected(0))

subscribeResult = client.SubscribeMarketData(
    "MNQ DEC26")  # start getting market data
print("Subscribe result:", subscribeResult)

time.sleep(2)

# Strategy parameters
TP_Ratio = 2
contract_size = 1
SLdivider = 650
trade_taken = False
position = None
stopLossOrder = None
takeProfitOrder = None
# Candle data points
bar_start = None
open_price = None
high_price = None
low_price = None
close_price = None
candle_volume = None
starting_volume = None
candles = pd.DataFrame(
    columns=["Date", "Open", "High", "Low", "Close", "Volume"])
orbValuesSet = False

try:
    while True:  # repeatedly grab market data
        last = client.MarketData("MNQ DEC26", 0)
        volume = client.MarketData("MNQ DEC26", 6)
        current_time = datetime.now()
        minute5candle = (current_time.minute // 5) * 5
        current5mperiod = current_time.replace(minute=minute5candle, second=0, microsecond=0)

        # the program will only keep track of the candles that are after 6:30 AM; market open
        if (current_time.time() < pd.to_datetime("6:30").time()):
            print("Not running yet")
            continue

        if current_time.time() >= pd.to_datetime("13:00").time():
            candles = pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
            bar_start = None
            open_price = None
            high_price = None
            low_price = None
            close_price = None
            candle_volume = None
            starting_volume = None
            orbValuesSet = False
            ORB_High, ORB_Low, ORB_Range = None
            liquidatePositions(position, stopLossOrder, takeProfitOrder)
            position = None
            break
        elif current_time.time() >= pd.to_datetime("8:15").time():
            trade_taken = True

        if position != None:
            sl_status = client.OrderStatus(stopLossOrder)
            tp_status = client.OrderStatus(takeProfitOrder)

            if sl_status == "Filled" or tp_status == "Filled":
                position = None

        if bar_start == None:  # if the first candle has yet to be set, then set each value to whatever is currently the price
            bar_start = current5mperiod
            open_price = last
            high_price = last
            low_price = last
            close_price = last
            starting_volume = volume
        elif current5mperiod != bar_start:  # when the current time changes 5m interval, then print the values and start a new candle and save the previous candle data in the dataframe
            candle_volume = volume - starting_volume
            new_row = {
                "Date": [bar_start],
                "Open": [open_price],
                "High": [high_price],
                "Low": [low_price],
                "Close": [close_price],
                "Volume": [candle_volume]
            }
            new_row = pd.DataFrame(new_row)
            candles = pd.concat([
                candles,
                new_row
            ])
            print("Bar:", bar_start, "Open:", open_price, "High:", high_price,
                  "Low:", low_price, "Close:", close_price, "Volume:", candle_volume)

            # when the first three 5m candles (15m) are stored, set the ORB high and low
            if len(candles) == 3 and orbValuesSet == False:
                ORB_High = candles["High"].max()
                ORB_Low = candles["Low"].min()
                ORB_Range = ORB_High - ORB_Low
                orbValuesSet = True

             # check for breakouts
            if orbValuesSet == True and trade_taken == False:
                marketOrder = client.NewOrderId()
                stopLossOrder = client.NewOrderId()
                takeProfitOrder = client.NewOrderId()
                oco_Id = client.NewOrderId()
                if candles.iloc[-1]["Close"] > ORB_High:
                    position = "long"
                    trade_taken = executeTrade(position, marketOrder, stopLossOrder, takeProfitOrder, oco_Id)
                elif candles.iloc[-1]["Close"] < ORB_Low:
                    position = "short"
                    trade_taken = executeTrade(position, marketOrder, stopLossOrder, takeProfitOrder, oco_Id)
            bar_start = current5mperiod
            open_price = last
            high_price = last
            low_price = last
            close_price = last
            starting_volume = volume
        else:  # check if the highs and lows change
            if last > high_price:
                high_price = last
            if last < low_price:
                low_price = last
            close_price = last
        time.sleep(1)


except KeyboardInterrupt:  # when program stops or is interrupted by input
    print("Stopping")

finally:
    client.UnsubscribeMarketData("MNQ DEC26")
    client.TearDown()
    # shut down connection to NinjaTrader
