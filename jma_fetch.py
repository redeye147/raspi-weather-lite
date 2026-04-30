"""
jma_fetch.py
データ取得専用
"""

import requests


def fetch_openmeteo(lat, lon):

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        "&hourly=weathercode,precipitation,temperature_2m,windspeed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"
        "&timezone=Asia/Tokyo"
    )

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    return r.json()


def fetch_jma(office_code):

    url = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{office_code}.json"

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    return r.json()
