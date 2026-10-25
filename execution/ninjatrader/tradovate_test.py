import os
import json
import requests
import websocket
from dotenv import load_dotenv

#load credentials
load_dotenv()

username = os.getenv("TRADOVATE_USERNAME")
password = os.getenv("TRADOVATE_PASSWORD")
cid = os.getenv("TRADOVATE_CID")
secret = os.getenv("TRADOVATE_SECRET")
app_id = os.getenv("TRADOVATE_APP_ID")
app_version = os.getenv("TRADOVATE_APP_VERSION")

#authenticate
auth_url = "https://demo.tradovateapi.com/v1/auth/accesstokenrequest"

credentials = {
    "name": username,
    "password": password,
    "appId": app_id,
    "appVersion": app_version,
    "cid": cid,
    "sec": secret
}

response = requests.post(auth_url, json=credentials)
response.raise_for_status()

auth_data = response.json()

access_token = auth_data["accessToken"]
md_access_token = auth_data["mdAccessToken"]

print("Authentication successful")

#account test
headers = {
    "Authorization": f"Bearer {access_token}"
}

account_response = requests.get(
    "https://demo.tradovateapi.com/v1/account/list",
    headers=headers
)

account_response.raise_for_status()

print("Account access successful")

#websocket
chart_requested = False
chart_request_id = 1

#subscribe to data
def subscribe_to_chart(ws):
    global chart_requested

    chart_request = {
        "symbol": "MNQZ6",
        "chartDescription": {
            "underlyingType": "MinuteBar",
            "elementSize": 5,
            "elementSizeUnit": "UnderlyingUnits",
            "withHistogram": False
        },
        "timeRange": {
            "asMuchAsElements": 20
        }
    }

    message = (
        "md/getChart\n"
        f"{chart_request_id}\n\n"
        + json.dumps(chart_request)
    )

    ws.send(message)

    chart_requested = True

    print("5-minute MNQ chart requested")

#callbacks
def on_open(ws):
    print("WebSocket opened")

    auth_message = f"authorize\n0\n\n{md_access_token}"

    ws.send(auth_message)

def on_message(ws, message):
    global chart_requested

    # Tradovate server heartbeat
    if message == "h":
        ws.send("[]")
        return

    # Socket successfully opened
    if message == "o":
        print("Tradovate socket session opened")
        return

    # Tradovate wraps responses in a[...]
    if message.startswith("a"):
        responses = json.loads(message[1:])

        for response_data in responses:

            request_id = response_data.get("i")
            status = response_data.get("s")

            # Authorization response
            if request_id == 0:
                if status == 200:
                    print("Market data authorization successful")

                    if not chart_requested:
                        subscribe_to_chart(ws)

                else:
                    print("Authorization failed:", response_data)

            # md/getChart response
            elif request_id == chart_request_id:
                if status == 200:
                    data = response_data.get("d", {})

                    print("Chart subscription successful")
                    print("Historical ID:", data.get("historicalId"))
                    print("Realtime ID:", data.get("realtimeId"))

                else:
                    print("Chart request failed:", response_data)

        return

    # Market-data events
    if message.startswith("e"):
        events = json.loads(message[1:])

        for event in events:

            if event.get("e") == "chart":

                chart_data = event.get("d", {})

                for chart in chart_data.get("charts", []):

                    for bar in chart.get("bars", []):

                        timestamp = bar.get("timestamp")
                        open_price = bar.get("open")
                        high_price = bar.get("high")
                        low_price = bar.get("low")
                        close_price = bar.get("close")

                        up_volume = bar.get("upVolume", 0)
                        down_volume = bar.get("downVolume", 0)

                        volume = up_volume + down_volume

                        print(
                            "Bar:",
                            timestamp,
                            "Open:", open_price,
                            "High:", high_price,
                            "Low:", low_price,
                            "Close:", close_price,
                            "Volume:", volume
                        )

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print(
        "WebSocket closed:",
        close_status_code,
        close_msg
    )

#market data
ws = websocket.WebSocketApp(
    "wss://md.tradovateapi.com/v1/websocket",
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)

ws.run_forever()