import yfinance as yf

print("yfinance:", yf.__version__)

data = yf.download(
    "NQ=F",
    period="2m",
    interval="5m",
    progress=False
)

print(data)