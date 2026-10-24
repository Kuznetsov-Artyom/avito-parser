"""Геокодирование через OpenStreetMap Nominatim + расстояние haversine."""

from __future__ import annotations

import math
import time

import httpx

USER_AGENT = "avito-parser-personal/1.0 (personal use)"

# Простой in-memory кэш: текст -> (lat, lng, отображаемое имя)
_geocode_cache: dict[str, tuple[float, float, str]] = {}
_last_nominatim_call = 0.0  # Nominatim разрешает не чаще 1 запроса/сек


async def geocode(query: str) -> tuple[float, float, str] | None:
    """Геокодирует город/адрес. Возвращает (lat, lng, display_name) или None."""
    key = query.strip().lower()
    if not key:
        return None
    if key in _geocode_cache:
        return _geocode_cache[key]

    global _last_nominatim_call
    wait = 1.0 - (time.monotonic() - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)

    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "accept-language": "ru"},
        )
        _last_nominatim_call = time.monotonic()
        resp.raise_for_status()
        data = resp.json()

    if not data:
        return None
    hit = data[0]
    result = (float(hit["lat"]), float(hit["lon"]), hit.get("display_name", query))
    _geocode_cache[key] = result
    return result


async def reverse_geocode(lat: float, lng: float) -> dict | None:
    """Определяет город по координатам. Возвращает {"city": имя, "display": адрес} или None."""
    cache_key = f"rev:{round(lat, 3)},{round(lng, 3)}"
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    global _last_nominatim_call
    wait = 1.0 - (time.monotonic() - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)

    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json",
                        "zoom": 10, "accept-language": "ru"},
            )
            _last_nominatim_call = time.monotonic()
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 - Nominatim недоступен
        return None

    if data.get("error"):
        return None
    addr = data.get("address", {})
    city = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("municipality") or addr.get("county"))
    result = {"city": city, "display": data.get("display_name", "")}
    _geocode_cache[cache_key] = result
    return result


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Расстояние между двумя точками по поверхности Земли, км."""
    r = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
