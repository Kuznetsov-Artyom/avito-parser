"""Отладочная проверка: новый экстрактор страницы поиска (с продавцом)."""

import asyncio
import logging
import sys

sys.path.insert(0, ".")

from app.parser.browser import browser
from app.parser.search import parse_search_page
from app.parser.urls import build_search_url

logging.basicConfig(level=logging.WARNING)


async def main() -> None:
    page = await browser.new_page()
    try:
        url = build_search_url("велосипед", "moskva", 5000, 60000)
        listings = await parse_search_page(page, url, 8)
        print(f"=== {len(listings)} объявлений ===")
        for l in listings:
            s = l.seller
            print(f"[{l.avito_id}] {l.title[:40]!r} | {l.price}₽ | {l.location_text!r}")
            print(f"    продавец: {s.name!r} | рейтинг {s.rating} | отзывов {s.reviews} | бейджи {s.badges}")
            print(f"    описание: {(l.description or '')[:70]!r}")
    finally:
        await page.close()
        await browser.close()


asyncio.run(main())
