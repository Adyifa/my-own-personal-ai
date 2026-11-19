"""Weather from Open-Meteo: free, no API key, geocoding included."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..text import normalize

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes → Indonesian descriptions.
WMO_CODES = {
    0: "cerah", 1: "cerah berawan", 2: "berawan", 3: "mendung",
    45: "berkabut", 48: "berkabut",
    51: "gerimis", 53: "gerimis", 55: "gerimis cukup deras", 56: "gerimis dingin", 57: "gerimis dingin",
    61: "hujan ringan", 63: "hujan sedang", 65: "hujan lebat", 66: "hujan dingin", 67: "hujan dingin lebat",
    71: "salju ringan", 73: "salju", 75: "salju lebat", 77: "butiran salju",
    80: "hujan lokal ringan", 81: "hujan lokal", 82: "hujan lokal lebat",
    85: "hujan salju", 86: "hujan salju lebat",
    95: "badai petir", 96: "badai petir disertai es", 99: "badai petir disertai es",
}
_NOT_A_PLACE = {
    "cuaca", "prakiraan", "ramalan", "gimana", "bagaimana", "kayak", "kaya", "apa", "seperti", "hari", "ini", "besok",
    "lusa", "sekarang", "nanti", "suhu", "berapa", "derajat", "bakal", "akan", "mau", "apakah", "hujan", "nggak", "gak",
    "ga", "enggak", "tidak", "ngga", "kah", "dong", "ya", "mika", "tolong", "cek", "info", "di", "cerah", "panas", "dingin",
    "mendung", "lagi", "sedang", "turun", "nya", "kira", "perlu", "bawa", "payung", "untuk", "buat", "yang", "kota",
    "daerah", "wilayah", "sana", "sini", "pagi", "siang", "sore", "malam", "udara", "temperatur",
}


@dataclass
class Place:
    """A geocoded location."""

    name: str
    latitude: float
    longitude: float
    region: str = ""


@dataclass
class WeatherReport:
    """Spoken summary, screen detail, and the raw numbers for the LLM."""

    ok: bool
    spoken: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def parse_weather_request(text: str) -> tuple[str | None, int]:
    """("bandung", 1) from "cuaca di bandung besok gimana"; location None means the default city."""
    t = normalize(text)
    day = 2 if re.search(r"\blusa\b", t) else 1 if re.search(r"\bbesok\b", t) else 0
    at = re.search(r"\bdi\s+(.+)$", t)
    source = at.group(1) if at else t
    words = [
        word for word in source.split()
        if word not in _NOT_A_PLACE and not (word.endswith("nya") and word[:-3] in _NOT_A_PLACE)  # "cuacanya"
    ]
    return (" ".join(words) or None), day


def describe(code: int | None) -> str:
    """Indonesian description of a WMO weather code."""
    return WMO_CODES.get(int(code), "berawan") if code is not None else "tidak diketahui"


class WeatherService:
    """Geocode a city (cached), fetch a 3-day forecast, and phrase it for speech."""

    def __init__(self, config: dict[str, Any], *, client: httpx.Client | None = None):
        cfg = config.get("weather", {})
        self.default_location = str(cfg.get("location", "Jakarta"))
        self.country_code = str(cfg.get("country_code", "ID"))
        self.timeout = float(cfg.get("timeout_seconds", 5))
        self._client = client
        self._places: dict[str, Place | None] = {}

    @property
    def client(self) -> httpx.Client:
        """Created on first use: building a TLS client costs ~0.2 s that startup should not pay."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, headers={"User-Agent": "MikaAssistant/2.0"})
        return self._client

    def warm_up(self) -> None:
        """Look up the default city at startup: the first request pays DNS + TLS + geocoding (~2.5 s vs ~0.7 s)."""
        try:
            self.geocode(self.default_location)
        except (httpx.HTTPError, ValueError, KeyError):
            pass

    def geocode(self, name: str) -> Place | None:
        """Look up a city, preferring the configured country, then anywhere."""
        key = normalize(name)
        if key in self._places:
            return self._places[key]
        place = None
        for country in (self.country_code, ""):
            params: dict[str, Any] = {"name": name, "count": 1, "language": "id", "format": "json"}
            if country:
                params["countryCode"] = country
            response = self.client.get(GEOCODE_URL, params=params)
            response.raise_for_status()
            results = response.json().get("results") or []
            if results:
                row = results[0]
                place = Place(
                    name=re.sub(r"^(Kota|Kabupaten)\s+", "", str(row.get("name", name))),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    region=str(row.get("admin1", "")),
                )
                break
        self._places[key] = place
        return place

    def forecast(self, place: Place) -> dict[str, Any]:
        """Current conditions plus 3 daily forecasts in the place's own timezone."""
        response = self.client.get(
            FORECAST_URL,
            params={
                "latitude": place.latitude,
                "longitude": place.longitude,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 3,
            },
        )
        response.raise_for_status()
        return response.json()

    def report(self, location: str | None = None, day: int = 0) -> WeatherReport:
        """Weather for a city and day (0 today, 1 tomorrow, 2 the day after); never raises."""
        name = location or self.default_location
        try:
            place = self.geocode(name)
            if place is None:
                return WeatherReport(False, f"Mika nggak nemu lokasi {name}.")
            data = self.forecast(place)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return WeatherReport(False, "Mika nggak bisa ambil data cuaca sekarang. Sepertinya internetnya lagi bermasalah.", data={"error": str(exc)})
        return _phrase(place, data, max(0, min(day, 2)))


def _phrase(place: Place, data: dict[str, Any], day: int) -> WeatherReport:
    """Turn Open-Meteo JSON into 2-3 spoken sentences plus a detailed screen version."""
    daily = data.get("daily", {})
    current = data.get("current", {})

    def daily_value(key: str, index: int) -> Any:
        """One day's value from a daily series, or None if missing."""
        values = daily.get(key) or []
        return values[index] if index < len(values) else None

    tmin, tmax = daily_value("temperature_2m_min", day), daily_value("temperature_2m_max", day)
    rain = daily_value("precipitation_probability_max", day)
    condition = describe(daily_value("weather_code", day))
    rain_text = f", peluang hujan {round(rain)} persen" if rain is not None else ""
    range_text = f"{round(tmin)} sampai {round(tmax)} derajat" if tmin is not None and tmax is not None else ""

    if day == 0:
        now_temp = current.get("temperature_2m")
        now_text = describe(current.get("weather_code"))
        sentences = [f"Di {place.name} sekarang {round(now_temp)} derajat, {now_text}." if now_temp is not None else f"Cuaca {place.name} hari ini {condition}."]
        if range_text:
            sentences.append(f"Hari ini {range_text}{rain_text}.")
    else:
        label = "Besok" if day == 1 else "Lusa"
        sentences = [f"{label} di {place.name} diperkirakan {condition}, {range_text}{rain_text}.".replace(", .", ".")]
    if rain is not None and rain >= 60:
        sentences.append("Jangan lupa bawa payung, ya.")

    region = f", {place.region}" if place.region and normalize(place.region) not in normalize(place.name) else ""
    lines = [f"Cuaca {place.name}{region}"]
    if current:
        lines.append(
            f"Sekarang: {current.get('temperature_2m')}°C (terasa {current.get('apparent_temperature')}°C), "
            f"{describe(current.get('weather_code'))}, kelembapan {current.get('relative_humidity_2m')}%, "
            f"angin {current.get('wind_speed_10m')} km/jam"
        )
    for index, date in enumerate(daily.get("time") or []):
        lines.append(
            f"{date}: {describe(daily_value('weather_code', index))}, {daily_value('temperature_2m_min', index)}"
            f"-{daily_value('temperature_2m_max', index)}°C, hujan {daily_value('precipitation_probability_max', index)}%"
        )
    summary = {
        "lokasi": place.name,
        "hari": ["hari ini", "besok", "lusa"][day],
        "kondisi": condition,
        "suhu_min": tmin,
        "suhu_max": tmax,
        "peluang_hujan_persen": rain,
        "suhu_sekarang": current.get("temperature_2m"),
    }
    return WeatherReport(True, " ".join(sentences), "\n".join(lines), summary)
