
import json
import os
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

LATITUDE = 42.20
LONGITUDE = -74.23
LOCATION_NAME = "Hunter Mountain, NY"

TIMEZONE = ZoneInfo("America/New_York")

FORECAST_HOURS = 72
SNOW_ALERT_THRESHOLD_IN = 0.5

# Send a follow-up only if forecast snowfall increases
# by at least this much from the previous alert.
UPDATE_THRESHOLD_IN = 0.75

STATE_FILE = "snow_state.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


# --------------------------------------------------
# WEATHER FORECAST
# --------------------------------------------------

def get_forecast():
    """Retrieve hourly snow and temperature forecast."""

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "snowfall,temperature_2m",
        "forecast_days": 4,
        "timezone": "America/New_York",
        "temperature_unit": "fahrenheit",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    return response.json()


# --------------------------------------------------
# CALCULATE NEXT 72 HOURS
# --------------------------------------------------

def analyze_forecast(data):
    """Sum forecast snowfall during the next 72 hours."""

    hourly = data["hourly"]

    times = hourly["time"]
    snowfall_cm = hourly["snowfall"]
    temperatures = hourly["temperature_2m"]

    now = datetime.now(TIMEZONE)
    end_time = now + timedelta(hours=FORECAST_HOURS)

    total_cm = 0
    snow_periods = []
    snow_temps = []

    for time_str, snow_cm, temp_f in zip(
        times, snowfall_cm, temperatures
    ):

        forecast_time = datetime.fromisoformat(time_str)
        forecast_time = forecast_time.replace(tzinfo=TIMEZONE)

        if now <= forecast_time < end_time and snow_cm is not None:

            total_cm += snow_cm

            if snow_cm > 0:
                snow_periods.append(forecast_time)
                snow_temps.append(temp_f)

    total_inches = total_cm / 2.54

    if snow_periods:
        first_snow = min(snow_periods)
        last_snow = max(snow_periods)
        average_temp = sum(snow_temps) / len(snow_temps)
    else:
        first_snow = None
        last_snow = None
        average_temp = None

    return {
        "snow_inches": total_inches,
        "first_snow": first_snow,
        "last_snow": last_snow,
        "average_temp": average_temp,
        "checked_at": now,
    }


# --------------------------------------------------
# TELEGRAM NOTIFICATIONS
# --------------------------------------------------

def send_telegram_message(message):
    """Send a message to your Telegram chat."""

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError("Telegram failed to send message")


# --------------------------------------------------
# ALERT STATE
# --------------------------------------------------

def load_state():
    """Read previously saved alert information."""

    try:
        with open(STATE_FILE, "r") as file:
            return json.load(file)

    except FileNotFoundError:
        return {
            "active_alert": False,
            "last_alert_inches": 0,
        }


def save_state(state):
    """Persist alert information between runs."""

    with open(STATE_FILE, "w") as file:
        json.dump(state, file, indent=2)


# --------------------------------------------------
# FORMAT ALERT
# --------------------------------------------------

def format_alert(forecast, is_update=False):

    amount = forecast["snow_inches"]
    first = forecast["first_snow"]
    last = forecast["last_snow"]
    temp = forecast["average_temp"]

    title = "❄️ HUNTER MOUNTAIN SNOW ALERT"

    if is_update:
        title = "📈 HUNTER SNOW FORECAST UPDATE"

    message = (
        f"{title}\n\n"
        f"📍 {LOCATION_NAME}\n"
        f"🌨️ Forecast snowfall: {amount:.1f} inches\n"
        f"🕒 Forecast window: Next 72 hours\n"
    )

    if first and last:
        message += (
            f"\n❄️ Snow may begin: "
            f"{first.strftime('%a %b %d, %I:%M %p')}\n"
            f"❄️ Snow may continue through: "
            f"{last.strftime('%a %b %d, %I:%M %p')}\n"
        )

    if temp is not None:
        message += (
            f"\n🌡️ Average temperature during "
            f"forecast snow hours: {temp:.0f}°F\n"
        )

    message += (
        f"\n🔎 Forecast checked: "
        f"{forecast['checked_at'].strftime('%I:%M %p %Z')}\n"
        f"🌐 Source: Open-Meteo"
    )

    return message


# --------------------------------------------------
# MAIN AGENT
# --------------------------------------------------

def main():

    print("Checking Hunter Mountain forecast...")

    data = get_forecast()
    forecast = analyze_forecast(data)

    snow_inches = forecast["snow_inches"]

    print(
        f"Snow forecast in next 72 hours: "
        f"{snow_inches:.2f} inches"
    )

    state = load_state()

    active_alert = state.get("active_alert", False)
    previous_amount = state.get("last_alert_inches", 0)

    # ----------------------------------------------
    # SNOW FORECAST ABOVE ALERT THRESHOLD
    # ----------------------------------------------

    if snow_inches >= SNOW_ALERT_THRESHOLD:

        # First alert for this snow event
        if not active_alert:

            message = format_alert(forecast)
            send_telegram_message(message)

            state["active_alert"] = True
            state["last_alert_inches"] = snow_inches

            print("Initial snow alert sent.")

        # Send follow-up if snowfall forecast increases
        elif snow_inches >= previous_amount + UPDATE_THRESHOLD_IN:

            message = format_alert(
                forecast,
                is_update=True
            )

            send_telegram_message(message)

            state["last_alert_inches"] = snow_inches

            print("Updated snow alert sent.")

        else:
            print("No new alert. Forecast change is too small.")

    # ----------------------------------------------
    # FORECAST FALLS BELOW THRESHOLD
    # ----------------------------------------------

    else:

        if active_alert:
            print("Snow forecast dropped below threshold.")

        state["active_alert"] = False
        state["last_alert_inches"] = 0

    save_state(state)

    print("Agent completed successfully.")


if __name__ == "__main__":
    main()
