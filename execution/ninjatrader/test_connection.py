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

time.sleep(2)

try:
    while True: #repeatedly grab market data
        last = client.MarketData("MNQ DEC26", 0)
        bid = client.MarketData("MNQ DEC26", 1)
        ask = client.MarketData("MNQ DEC26", 2)

        print(f"Last: {last} | Bid: {bid} | Ask: {ask}") #print the data received

        time.sleep(1) #every second grab data

except KeyboardInterrupt: #when program stops or is interrupted by input
    print("Stopping...")

finally: 
    client.UnsubscribeMarketData("MNQ DEC26") 
    client.TearDown()
    #shut down connection NinjaTrader   
