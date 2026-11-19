"""Погода (Open-Meteo, без ключа) и курс валют (ЦБ РФ). Ответы сразу в виде фраз для озвучки."""
import datetime

import requests

WMO = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "изморозь и туман",
    51: "слабая морось", 53: "морось", 55: "сильная морось", 56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа", 80: "кратковременный дождь",
    81: "ливень", 82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад", 95: "гроза",
    96: "гроза с градом", 99: "сильная гроза с градом",
}
_geo_cache = {}


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def deg(t, gen=False):
    """gen=True — родительный падеж: «от 1 градуса», «до 5 градусов»."""
    t = round(t)
    sign = "плюс " if t > 0 else ("минус " if t < 0 else "")
    word = plural(t, "градуса", "градусов", "градусов") if gen else plural(t, "градус", "градуса", "градусов")
    return f"{sign}{abs(t)} {word}"


def _city_candidates(name):
    """«в балашихе» -> балашиха, «в москве» -> москва, «в казани» -> казань, «в новосибирске» -> новосибирск."""
    w = name.strip()
    alias = {"питере": "Санкт-Петербург", "питер": "Санкт-Петербург", "спб": "Санкт-Петербург",
             "петербурге": "Санкт-Петербург", "мск": "Москва"}
    if w.lower() in alias:
        return [alias[w.lower()]]
    c = [w]
    if w.endswith("е"):
        c += [w[:-1] + "а", w[:-1], w[:-1] + "я", w[:-1] + "о"]
    if w.endswith("и"):
        c += [w[:-1] + "ь", w[:-1] + "а", w[:-1] + "я"]
    if w.endswith("у"):
        c += [w[:-1] + "а"]
    return list(dict.fromkeys(c))


def geocode(name):
    key = name.lower()
    if key in _geo_cache:
        return _geo_cache[key]
    for cand in _city_candidates(name):
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": cand, "count": 5, "language": "ru"}, timeout=8)
        res = r.json().get("results") or []
        if res:
            res.sort(key=lambda x: (x.get("country_code") != "RU", -(x.get("population") or 0)))
            g = res[0]
            _geo_cache[key] = (g["latitude"], g["longitude"], g["name"])
            return _geo_cache[key]
    return None


def weather(city, day=0):
    g = geocode(city)
    if not g:
        return f"Не нашёл город {city}"
    lat, lon, name = g
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "timezone": "auto", "wind_speed_unit": "ms", "forecast_days": 3,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
    }, timeout=8).json()
    d = r["daily"]
    rain = d["precipitation_probability_max"][day]
    rain_txt = f", вероятность осадков {rain} {plural(rain, 'процент', 'процента', 'процентов')}" if rain else ""
    if day == 0:
        c = r["current"]
        wind = round(c["wind_speed_10m"])
        return (f"{name}: сейчас {deg(c['temperature_2m'])}, {WMO.get(c['weather_code'], 'без описания')}, "
                f"ощущается как {deg(c['apparent_temperature'])}, ветер {wind} {plural(wind, 'метр', 'метра', 'метров')} "
                f"в секунду. Днём до {deg(d['temperature_2m_max'][0], True)}{rain_txt}.")
    label = "Завтра" if day == 1 else "Послезавтра"
    return (f"{name}, {label.lower()}: от {deg(d['temperature_2m_min'][day], True)} до {deg(d['temperature_2m_max'][day], True)}, "
            f"{WMO.get(d['weather_code'][day], 'без описания')}{rain_txt}.")


CUR = {"USD": "доллара", "EUR": "евро", "CNY": "юаня"}


def currency(code="USD"):
    code = code.upper()
    data = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=8).json()
    v = data["Valute"][code]
    rub = v["Value"] / v["Nominal"]
    r, k = int(rub), round((rub - int(rub)) * 100)
    return (f"Курс {CUR.get(code, code)} по ЦБ: {r} {plural(r, 'рубль', 'рубля', 'рублей')} "
            f"{k} {plural(k, 'копейка', 'копейки', 'копеек')}")
