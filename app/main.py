"""FastAPI-приложение: API поиска, геокодирование, статика."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .geo import geocode, reverse_geocode
from .models import SearchRequest, SearchStatus, ScoredListing, Seller, Scores
from .parser.browser import browser
from .parser.suggest import avito_suggest
from .parser.urls import CITY_SUGGESTIONS, match_city_slug
from .pipeline import run_search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("avito.app")

STATIC_DIR = Path(__file__).parent / "static"

# Живые фоновые задачи поиска: search_id -> asyncio.Task
_tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield
    for task in _tasks.values():
        task.cancel()
    await browser.close()


app = FastAPI(title="Avito Parser", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/cities")
async def cities():
    """Список популярных городов для выпадающего списка."""
    return [{"slug": slug, "name": name} for slug, name in CITY_SUGGESTIONS]


@app.get("/api/geocode")
async def geocode_endpoint(q: str):
    """Геокодирование города/адреса через OpenStreetMap + подходящий город Avito."""
    if not q.strip():
        raise HTTPException(400, "Пустой запрос")
    try:
        result = await geocode(q)
    except Exception as e:  # noqa: BLE001 - Nominatim недоступен и т.п.
        raise HTTPException(502, f"Не удалось геокодировать: {e}")
    if result is None:
        raise HTTPException(404, "Место не найдено")
    lat, lng, name = result
    # из отображаемого имени Nominatim («Тверская 1, Москва, …») пробуем понять город
    city_name = _city_from_display(name)
    return {"lat": lat, "lng": lng, "name": name,
            "city_slug": match_city_slug(city_name), "city_name": city_name}


def _city_from_display(display_name: str) -> str | None:
    """Достаёт город из отображаемого имени Nominatim (город — 2-й или 3-й компонент)."""
    if not display_name:
        return None
    parts = [p.strip() for p in display_name.split(",")]
    # пропускаем дом/улицу слева и страну/регион справа
    for part in parts[1:]:
        slug = match_city_slug(part)
        if slug:
            return part
    return parts[1] if len(parts) > 1 else None


@app.get("/api/reverse")
async def reverse_endpoint(lat: float, lng: float):
    """Определяет город по координатам (для автоподстановки при геолокации)."""
    try:
        result = await reverse_geocode(lat, lng)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Не удалось определить город: {e}")
    if result is None or not result.get("city"):
        raise HTTPException(404, "Город не определён")
    city = result["city"]
    return {"city": city, "city_slug": match_city_slug(city),
            "display": result["display"]}


@app.get("/api/suggest")
async def suggest_endpoint(q: str):
    """Подсказки для строки поиска: живые подсказки Avito + история прошлых поисков."""
    q = q.strip()
    if len(q) < 2:
        return {"items": []}

    avito_items: list[dict] = []
    try:
        for text, kind in await avito_suggest(q):
            avito_items.append({"text": text, "kind": kind, "source": "avito"})
    except Exception as e:  # noqa: BLE001 - блокировка/недоступность — не критично
        log.info("avito suggest unavailable: %s", e)

    history = db.search_history(q, limit=5)
    seen = {i["text"].lower() for i in avito_items}
    history_items = [{"text": h, "kind": "history", "source": "history"} for h in history
                     if h.lower() not in seen]

    return {"items": (avito_items + history_items)[:10]}


@app.post("/api/search")
async def start_search(req: SearchRequest):
    """Создаёт задачу поиска и сразу возвращает её id."""
    if req.price_min and req.price_max and req.price_min > req.price_max:
        raise HTTPException(400, "Минимальная цена больше максимальной")

    # геопозиция текстом -> координаты (если пользователь не прислал координаты сам)
    if (req.user_lat is None or req.user_lng is None) and req.user_location:
        try:
            geo = await geocode(req.user_location)
        except Exception:  # noqa: BLE001 - геокодинг не критичен, сортируем без расстояния
            geo = None
        if geo:
            req.user_lat, req.user_lng = geo[0], geo[1]

    search_id = db.create_search(req.query, req.city, req.model_dump())
    task = asyncio.create_task(run_search(search_id, req))
    _tasks[search_id] = task
    task.add_done_callback(lambda t: _tasks.pop(search_id, None))
    return {"id": search_id}


@app.get("/api/search/{search_id}", response_model=SearchStatus)
async def search_status(search_id: str):
    row = db.get_search(search_id)
    if row is None:
        raise HTTPException(404, "Поиск не найден")

    status = SearchStatus(
        id=row["id"],
        status=row["status"],
        total=row["total"],
        processed=row["processed"],
        current_step=row["current_step"],
        error=row["error"],
    )
    if row["status"] == "done":
        for d in db.get_listings(search_id):
            status.results.append(ScoredListing(
                avito_id=d["avito_id"],
                title=d["title"] or "",
                price=d["price"],
                url=d["url"] or "",
                image_url=d["image_url"],
                location_text=d["location_text"],
                distance_km=d["distance_km"],
                description=d["description"],
                seller=Seller(
                    name=d["seller_name"],
                    rating=d["seller_rating"],
                    reviews=d["seller_reviews"],
                    member_since=d["seller_since"],
                    badges=d.get("seller_badges") or [],
                ),
                scores=Scores(
                    reliability=d["rel_score"] or 0.0,
                    price=d["price_score"] or 0.0,
                    distance=d["dist_score"] or 0.0,
                    total=d["total_score"] or 0.0,
                ),
            ))
    return status


def main() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=False)


if __name__ == "__main__":
    main()
