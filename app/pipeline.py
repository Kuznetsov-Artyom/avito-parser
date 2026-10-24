"""Фоновый конвейер: страница поиска -> (опц. deep scan объявлений) -> координаты -> скоринг -> БД."""

from __future__ import annotations

import logging

from . import db
from .config import settings
from .geo import haversine_km
from .models import Listing, SearchRequest
from .parser.browser import browser, page_delay
from .parser.item import parse_item_page
from .parser.search import parse_search_page
from .parser.urls import CITY_SUGGESTIONS, build_search_url
from .scoring import score_all

log = logging.getLogger("avito.pipeline")


async def _fill_coords_by_geocoding(listings: list[Listing], city_slug: str) -> None:
    """Проставляет координаты через Nominatim по тексту района («Ховрино» + город).

    Уникальных районов обычно немного, кэш геокодера экономит запросы.
    """
    from .geo import geocode  # импорт внутри, чтобы не тянуть httpx в тесты скоринга

    city_names = {slug: name for slug, name in CITY_SUGGESTIONS}
    city_name = city_names.get(city_slug, city_slug.replace("_", " ").title())

    for listing in listings:
        if listing.lat is not None or not listing.location_text:
            continue
        # «Ховрино, до 5 мин.» -> «Ховрино»; «Москва, м. Тверская» -> берём часть после города
        place = listing.location_text.split(",")[0].strip()
        if not place or place.lower() == city_name.lower():
            continue
        try:
            geo = await geocode(f"{place}, {city_name}")
        except Exception:  # noqa: BLE001 - Nominatim недоступен: расстояние будет нейтральным
            geo = None
        if geo:
            listing.lat, listing.lng = geo[0], geo[1]


async def run_search(search_id: str, req: SearchRequest) -> None:
    """Основная фоновая задача поиска. Обновляет статусы в БД по ходу работы."""
    page = None
    try:
        db.update_search(search_id, status="running", current_step="Открываем страницу поиска…")
        page = await browser.new_page()

        url = build_search_url(req.query, req.city, req.price_min, req.price_max)
        listings = await parse_search_page(page, url, req.max_items)

        if not listings:
            db.update_search(search_id, status="done", total=0, processed=0,
                             current_step=None,
                             error="Ничего не найдено. Проверьте запрос, город и фильтры цены.")
            return

        db.update_search(search_id, total=len(listings),
                         current_step=f"Найдено {len(listings)} объявлений")

        # deep scan: открываем каждое объявление (возраст аккаунта, точные координаты,
        # бейджи). По умолчанию выключен: всё главное уже есть в карточках поиска,
        # а каждый визит повышает риск блокировки.
        if settings.deep_scan:
            for i, base in enumerate(listings):
                db.update_search(search_id, processed=i,
                                 current_step=f"Обрабатываем объявление {i + 1} из {len(listings)}")
                try:
                    listing = await parse_item_page(page, base)
                except Exception as e:  # noqa: BLE001 - одно объявление не должно ронять поиск
                    log.warning("item %s failed: %s", base.avito_id, e)
                    listing = base
                # данные из карточки поиска не теряем, если на странице объявления их нет
                if not listing.seller.rating:
                    listing.seller.rating = base.seller.rating
                if not listing.seller.reviews:
                    listing.seller.reviews = base.seller.reviews
                if not listing.seller.badges:
                    listing.seller.badges = base.seller.badges
                listings[i] = listing
                if i < len(listings) - 1:
                    await page_delay()

        db.update_search(search_id, processed=len(listings),
                         current_step="Определяем координаты районов…")
        await _fill_coords_by_geocoding(listings, req.city)

        db.update_search(search_id, current_step="Считаем баллы…")
        scores = score_all(listings, req, settings.distance_radius_km)
        for listing, sc in zip(listings, scores):
            dist = None
            if req.user_lat is not None and req.user_lng is not None and listing.lat and listing.lng:
                dist = round(haversine_km(req.user_lat, req.user_lng, listing.lat, listing.lng), 1)
            db.save_listing(search_id, {
                "avito_id": listing.avito_id,
                "title": listing.title,
                "price": listing.price,
                "url": listing.url,
                "image_url": listing.image_url,
                "location_text": listing.location_text,
                "lat": listing.lat,
                "lng": listing.lng,
                "distance_km": dist,
                "description": listing.description,
                "seller_name": listing.seller.name,
                "seller_rating": listing.seller.rating,
                "seller_reviews": listing.seller.reviews,
                "seller_since": listing.seller.member_since,
                "seller_badges": listing.seller.badges,
                "rel_score": sc.reliability,
                "price_score": sc.price,
                "dist_score": sc.distance,
                "total_score": sc.total,
            })

        db.update_search(search_id, status="done", current_step=None)
        log.info("search %s done: %d listings", search_id, len(listings))

    except Exception as e:  # noqa: BLE001 - любая ошибка уходит в статус задачи
        log.exception("search %s failed", search_id)
        db.update_search(search_id, status="error", error=str(e)[:500], current_step=None)
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
