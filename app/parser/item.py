"""Парсинг страницы объявления Avito: продавец, координаты, описание."""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..models import Listing, Seller
from .browser import goto

log = logging.getLogger("avito.parser.item")

# Основной extraction-скрипт. Селекторы Avito часто меняются, поэтому
# для каждого поля несколько запасных вариантов + разбор текста регулярками.
_EXTRACT_JS = r"""
() => {
  const result = {
    title: null, price: null, description: null, location: null,
    sellerName: null, rating: null, reviews: null, since: null, badges: [],
    lat: null, lng: null,
  };
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // --- Заголовок и цена ---
  const titleEl = $('h1[data-marker="item-view/title-info-title"], h1.title');
  if (titleEl) result.title = titleEl.textContent.trim();
  const priceEl = $('[data-marker="item-view/title-info/price"], span[data-marker="item-price"]');
  if (priceEl) {
    const m = priceEl.textContent.replace(/\u00a0/g, ' ').match(/(\d[\d\s]*)/);
    if (m) result.price = parseInt(m[1].replace(/\s/g, ''), 10);
  }

  // --- Описание ---
  const descEl = $('div[itemprop="description"], [data-marker="item-view/item-description"]');
  if (descEl) result.description = descEl.textContent.trim().slice(0, 400);

  // --- Адрес (текст) ---
  const addrEl = $('[class*="style-item-address__string"], [data-marker="item-address"], p[class*="address"]');
  if (addrEl) result.location = addrEl.textContent.trim();

  // --- Блок продавца ---
  let sellerEl = $('[data-marker="item-view/seller-info"], [data-marker="seller-info"], ' +
                   '[class*="style-seller-info"], [data-marker="item-card-seller-info"]');
  let sellerText = '';
  if (sellerEl) sellerText = sellerEl.innerText;

  // имя: отдельный элемент или первая строка блока
  const nameEl = $('[data-marker="seller-info/name"]');
  if (nameEl) result.sellerName = nameEl.textContent.trim();
  else if (sellerEl) {
    const first = sellerText.split('\n').map(s => s.trim()).filter(Boolean)[0];
    if (first && !/^\d/.test(first)) result.sellerName = first;
  }

  // рейтинг: «4.8» или «Рейтинг 4,8» — одно- или двухзначное число до 5
  if (sellerText) {
    const rm = sellerText.replace(',', '.').match(/(?:рейтинг[:\s]*)?([0-5]\.\d)/i);
    if (rm) result.rating = parseFloat(rm[1]);
    const revm = sellerText.match(/(\d+)\s*(?:отзыв|отзывов|отзыва)/i);
    if (revm) result.reviews = parseInt(revm[1], 10);
    const sm = sellerText.match(/на\s*avito\s*с\s*(\d{4})/i);
    if (sm) result.since = parseInt(sm[1], 10);
  }

  // --- Бейджи: ищем известные маркеры надёжности по всему тексту страницы ---
  const bodyText = document.body.innerText;
  const known = ['Авито Доставка', 'Документы проверены', 'Проверенное Avito',
                 'Товар проверен Avito', 'Авито Премиум', 'Магазин проверен Avito',
                 'Данные подтверждены', 'Реквизиты проверены'];
  for (const badge of known) {
    if (bodyText.includes(badge)) result.badges.push(badge);
  }

  // --- Координаты: ищем {lat, lng} в глобальных данных страницы ---
  try {
    for (const key of ['__initialData__', '__staticRouterHydrationData__']) {
      const data = window[key];
      if (!data) continue;
      const found = [];
      const walk = (node, depth) => {
        if (!node || typeof node !== 'object' || depth > 25 || found.length) return;
        if (Array.isArray(node)) { for (const x of node) walk(x, depth + 1); return; }
        const hasLat = ('lat' in node || 'latitude' in node);
        const hasLng = ('lng' in node || 'lon' in node || 'longitude' in node);
        if (hasLat && hasLng) {
          const lat = Number(node.lat ?? node.latitude);
          const lng = Number(node.lng ?? node.lon ?? node.longitude);
          if (Number.isFinite(lat) && Number.isFinite(lng) &&
              Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
            found.push([lat, lng]);
          }
        }
        for (const key of Object.keys(node)) walk(node[key], depth + 1);
      };
      walk(data, 0);
      if (found.length) { result.lat = found[0][0]; result.lng = found[0][1]; }
    }
  } catch (e) { /* структура изменилась — не критично */ }

  return result;
}
"""


def _parse_listing(avito_id: str, url: str, data: dict, base: Listing | None) -> Listing:
    seller = Seller(
        name=data.get("sellerName"),
        rating=data.get("rating"),
        reviews=data.get("reviews"),
        member_since=data.get("since"),
        badges=[b for b in (data.get("badges") or []) if b],
    )
    return Listing(
        avito_id=avito_id,
        title=(data.get("title") or (base.title if base else "") or ""),
        price=data.get("price") or (base.price if base else None),
        url=url,
        image_url=base.image_url if base else None,
        location_text=data.get("location") or (base.location_text if base else None),
        lat=data.get("lat"),
        lng=data.get("lng"),
        description=data.get("description"),
        seller=seller,
    )


async def parse_item_page(page: Page, base: Listing) -> Listing:
    """Открывает страницу объявления и дополняет карточку данными о продавце и координатами."""
    await goto(page, base.url)
    try:
        await page.wait_for_selector('h1', timeout=10_000)
    except Exception:  # noqa: BLE001 - страница всё равно могла загрузиться
        log.debug("h1 not found on %s", base.url)
    data = await page.evaluate(_EXTRACT_JS)
    listing = _parse_listing(base.avito_id, base.url, data, base)
    log.debug("item %s: rating=%s reviews=%s since=%s coords=%s,%s",
              base.avito_id, seller_rating(listing), seller_reviews(listing),
              listing.seller.member_since, listing.lat, listing.lng)
    return listing


def seller_rating(l: Listing) -> float | None:
    return l.seller.rating


def seller_reviews(l: Listing) -> int | None:
    return l.seller.reviews
