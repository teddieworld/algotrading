import clr
import time

clr.AddReference(r"C:\Program Files\NinjaTrader 8\bin\NinjaTrader.Client.dll") #load ninjatrader client
from NinjaTrader.Client import Client


client = Client() #create a Client object



result = client.SetUp("127.0.0.1", 36973) #connect to NinjaTrader
print("SetUp result:", result)
print("Connected:", client.Connected(0))


subscribeResult = client.SubscribeMarketData("MNQ DEC26") #start getting market data
print("Subscribe result:", subscribeResult)



marketOrder = client.NewOrderId()
stopLossOrder = client.NewOrderId()
takeProfitOrder = client.NewOrderId()
oco_Id = client.NewOrderId()

entry_result = client.Command(
    "PLACE",
    "DEMO7641540",
    "MNQ DEC26",
    "BUY",
    1,
    "MARKET",
    0,
    0,
    "DAY",
    "",
    marketOrder,
    "",
    ""
)
print("Entry result:", entry_result)
order_status = client.OrderStatus(marketOrder) #get the status of an open order
filled = client.Filled(marketOrder) #check if the order has been filled

sl_result = client.Command(
    "PLACE",
    "DEMO7641540",
    "MNQ DEC26",
    "SELL",
    1,
    "STOPMARKET",
    0,
    30090,
    "DAY",
    oco_Id,
    stopLossOrder,
    "",
    ""
)

tp_result = client.Command(
    "PLACE",
    "DEMO7641540",
    "MNQ DEC26",
    "SELL",
    1,
    "LIMIT",
    30095,
    0,
    "DAY",
    oco_Id,
    takeProfitOrder,
    "",
    ""
)

print("Entry result:", entry_result)
print("SL result:", sl_result)
print("TP result:", tp_result)

time.sleep(1)

print("Entry status:", client.OrderStatus(marketOrder))
print("SL status:", client.OrderStatus(stopLossOrder))
print("TP status:", client.OrderStatus(takeProfitOrder))
print("Entry filled:", client.Filled(marketOrder))
print("SL filled:", client.Filled(stopLossOrder))
print("TP filled:", client.Filled(takeProfitOrder))





try:
    while True: #repeatedly grab market data
        last = client.MarketData("MNQ DEC26", 0)

        time.sleep(1) #every second grab data

except KeyboardInterrupt: #when program stops or is interrupted by input
    print("Stopping")

finally: 
    client.UnsubscribeMarketData("MNQ DEC26") 
    client.TearDown()
    #shut down connection to NinjaTrader   

