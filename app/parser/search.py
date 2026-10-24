"""Парсинг страницы поиска Avito.

В редизайне Avito карточка поиска уже содержит всё важное: цену, район,
имя продавца, рейтинг, число отзывов и бейджи — поэтому по умолчанию
страницы объявлений можно не открывать вовсе (см. DEEP_SCAN в config).
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..models import Listing, Seller
from .browser import goto
from .urls import build_item_url

log = logging.getLogger("avito.parser.search")

# Извлечение карточек прямо в браузере (JS быстрее, чем перенос DOM в Python)
_EXTRACT_JS = """
() => {
  const cards = document.querySelectorAll('div[data-marker="item"]');
  const out = [];
  for (const card of cards) {
    const id = card.getAttribute('data-item-id');
    if (!id) continue;

    const titleEl = card.querySelector('a[data-marker="item-title"]');
    const title = titleEl ? (titleEl.getAttribute('title') || titleEl.textContent.trim()) : '';
    const href = titleEl ? titleEl.getAttribute('href') : null;
    if (!href) continue;

    // цена: надёжнее всего из meta itemprop=price
    let price = null;
    const priceMeta = card.querySelector('meta[itemprop="price"]');
    if (priceMeta) {
      price = parseInt(priceMeta.getAttribute('content'), 10);
    } else {
      const priceText = card.textContent.match(/(\\d[\\d\\s\\u00a0]*)\\s*₽/);
      if (priceText) price = parseInt(priceText[1].replace(/[\\s\\u00a0]/g, ''), 10);
    }

    const img = card.querySelector('img');
    const image = img ? (img.getAttribute('src') || img.getAttribute('data-src')) : null;

    // район/метро: «Ховрино, до 5 мин.»
    const locEl = card.querySelector('[data-marker="item-location"]');
    const location = locEl ? locEl.textContent.trim() : null;

    // рейтинг продавца: «5,0»
    const ratingEl = card.querySelector(
      '[data-marker="seller-info/score"], [data-marker="seller-rating/score"]');
    let rating = null;
    if (ratingEl) {
      const m = ratingEl.textContent.replace(',', '.').match(/([0-5]\\.\\d)/);
      if (m) rating = parseFloat(m[1]);
    }

    // отзывы: «9 отзывов» / «435 отзывов»
    const reviewsEl = card.querySelector(
      '[data-marker="seller-info/summary"], [data-marker="rating-caption/rating"]');
    let reviews = null;
    if (reviewsEl) {
      const m = reviewsEl.textContent.match(/(\\d+)\\s*отзыв/i);
      if (m) reviews = parseInt(m[1], 10);
    }

    // имя продавца: первая «не-числовая» строка блока рейтинга
    let sellerName = null;
    const ratingBlock = card.querySelector('[data-marker="seller-rating"]');
    if (ratingBlock) {
      const lines = ratingBlock.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
      sellerName = lines.find(
        l => !/^[0-5][.,]\\d$/.test(l) && !/отзыв/i.test(l) && l !== '·') || null;
    }

    // бейджи карточки: «Реквизиты проверены», «Продвинуто», ...
    const badges = Array.from(card.querySelectorAll('[data-marker^="badge-title"]'))
      .map(e => e.textContent.trim()).filter(Boolean);

    // короткое описание, если есть
    const descEl = card.querySelector('[class*="description"], [data-marker="item-line"]');
    const description = descEl ? descEl.textContent.trim().slice(0, 300) : null;

    out.push({id, title, price: isNaN(price) ? null : price, url: href, image,
              location, rating, reviews, sellerName, badges, description});
  }
  return out;
}
"""


async def parse_search_page(page: Page, url: str, limit: int) -> list[Listing]:
    """Открывает страницу поиска и возвращает до `limit` объявлений с данными продавца."""
    await goto(page, url)
    try:
        await page.wait_for_selector('div[data-marker="item"]', timeout=15_000)
    except Exception:  # noqa: BLE001 - селектор не появился: пустая выдача или смена вёрстки
        log.warning("items grid not found on %s", url)
        return []

    # немного скроллим, чтобы ленивые картинки проставили src
    await page.evaluate(
        "async () => { for (let y = 0; y <= 1200; y += 400) { window.scrollTo(0, y);"
        " await new Promise(r => setTimeout(r, 200)); } }")

    raw = await page.evaluate(_EXTRACT_JS)
    listings: list[Listing] = []
    seen: set[str] = set()
    for item in raw:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        listings.append(Listing(
            avito_id=str(item["id"]),
            title=(item.get("title") or "").strip(),
            price=item.get("price"),
            url=build_item_url(item.get("url") or ""),
            image_url=item.get("image"),
            location_text=item.get("location") or None,
            description=item.get("description"),
            seller=Seller(
                name=item.get("sellerName"),
                rating=item.get("rating"),
                reviews=item.get("reviews"),
                badges=[b for b in (item.get("badges") or []) if b],
            ),
        ))
        if len(listings) >= limit:
            break
    log.info("parsed %d listings from search page", len(listings))
    return listings
