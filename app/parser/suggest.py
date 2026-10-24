"""Живые подсказки поисковых запросов Avito.

Avito отдаёт подсказки только «своим» — поэтому мы открываем страницу avito.ru
в нашем браузере и делаем same-origin POST к внутреннему эндпоинту подсказок:
cookies и fingerprint браузера применяются автоматически.

Формат ответа: {"result": [
    {"bubble_group": {"items": [{"text": "велосипед"}, ...]}},   # дозапросы
    {"text_item": {"title": "Велосипеды", "description": ...}},  # категории
]}
"""

from __future__ import annotations

import asyncio
import json
import logging

from .browser import browser

log = logging.getLogger("avito.suggest")

# Кэш: запрос -> список (текст, тип) — живёт до перезапуска
_cache: dict[str, list[tuple[str, str]]] = {}

# JS, выполняемый на странице avito.ru: same-origin запрос к эндпоинту подсказок
_FETCH_JS = """
async (q) => {
  const r = await fetch('/web/3/suggest', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query: q, limit: 8}),
  });
  return {status: r.status, body: await r.text()};
}
"""


class _SuggestPage:
    """Держит одну вкладку на avito.ru для дешёвых повторных запросов."""

    def __init__(self) -> None:
        self._page = None
        self._lock = asyncio.Lock()

    async def get(self):
        async with self._lock:
            if self._page is None or self._page.is_closed():
                page = await browser.new_page()
                try:
                    await page.goto("https://www.avito.ru/", wait_until="domcontentloaded")
                    self._page = page
                except Exception:  # noqa: BLE001 - блокировка и т.п.
                    await page.close()
                    raise
            return self._page


_suggest_page = _SuggestPage()


def _parse(payload: dict) -> list[tuple[str, str]]:
    """Извлекает подсказки из ответа Avito: (текст, тип: query|category)."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def push(text: str | None, kind: str) -> None:
        text = (text or "").strip()
        if 2 <= len(text) <= 80 and text.lower() not in seen:
            seen.add(text.lower())
            out.append((text, kind))

    for item in payload.get("result", []):
        if not isinstance(item, dict):
            continue
        for sub in (item.get("bubble_group") or {}).get("items", []):
            if isinstance(sub, dict):
                push(sub.get("text"), "query")
        ti = item.get("text_item")
        if isinstance(ti, dict):
            push(ti.get("title"), "category")
    return out


async def avito_suggest(query: str) -> list[tuple[str, str]]:
    """Возвращает до 8 живых подсказок Avito по префиксу запроса."""
    query = query.strip()
    if len(query) < 2:
        return []
    if query.lower() in _cache:
        return _cache[query.lower()]

    page = await _suggest_page.get()
    result = await page.evaluate(_FETCH_JS, query)
    if result["status"] != 200:
        log.debug("avito suggest HTTP %s", result["status"])
        return []

    try:
        payload = json.loads(result["body"])
    except (ValueError, TypeError):
        return []

    items = [(t, k) for t, k in _parse(payload) if t.lower() != query.lower()][:8]
    if items:
        _cache[query.lower()] = items
    return items
