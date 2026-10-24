"""Общий код парсера Avito: браузер со stealth-настройками и детект блокировок.

Основной режим — Yandex Browser (или другой системный Chromium-браузер):
Playwright подключается к нему по CDP. У настоящего браузера честный fingerprint,
поэтому антибот Avito пропускает его гораздо охотнее, чем тестовый Chromium.
Запасной режим — встроенный Playwright Chromium.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import subprocess
import time

import httpx
from playwright.async_api import BrowserContext, Page, async_playwright

from ..config import PROFILE_DIR, settings

log = logging.getLogger("avito.parser")

# Признаки страницы блокировки/капчи Avito
_BLOCK_MARKERS = (
    "доступ ограничен",
    "доступ к авито временно ограничен",
    "подтвердите, что вы не робот",
    "index_captcha",
    "ваша безопасность важна для нас",
)

# Где ищем системный браузер (первый найденный используется)
_BROWSER_CANDIDATES = [
    os.environ.get("YANDEX_BROWSER_PATH", ""),
    "/usr/bin/yandex-browser-stable",
    "/usr/bin/yandex-browser",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]

# Скрытая автоматизация: системный браузер сам не помечен как тестовый,
# патчим только явный признак webdriver.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
"""


class BlockedError(RuntimeError):
    """Avito заблокировал запрос (капча/лимит)."""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_system_browser() -> str | None:
    for path in _BROWSER_CANDIDATES:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


async def _wait_cdp(port: int, timeout: float = 20.0) -> bool:
    """Ждём, пока браузер поднимет CDP-эндпоинт."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                r = await client.get(f"http://127.0.0.1:{port}/json/version")
                if r.status_code == 200:
                    return True
        except Exception:  # noqa: BLE001 - браузер ещё стартует
            await asyncio.sleep(0.3)
    return False


class AvitoBrowser:
    """Ленивый singleton: системный браузер через CDP, fallback — Playwright Chromium.

    Профиль персистентный (cookies сохраняются между запусками), со стороны Avito
    это выглядит как один и тот же обычный пользователь.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._context: BrowserContext | None = None
        self._proc: subprocess.Popen | None = None  # процесс системного браузера
        self._lock = asyncio.Lock()

    async def _start_system_browser(self) -> BrowserContext | None:
        binary = _find_system_browser()
        if binary is None:
            log.info("system browser not found, using bundled chromium")
            return None

        port = _free_port()
        profile = PROFILE_DIR / "yandex"
        profile.mkdir(parents=True, exist_ok=True)
        args = [
            binary,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--window-size=1440,900",
            "--window-position=32000,32000",  # окно «вне экрана», чтобы не мешало
        ]
        # по умолчанию — видимый режим (DISPLAY есть), т.к. headless детектится;
        # можно принудительно включить headless через .env
        if os.environ.get("BROWSER_HEADLESS", "0") == "1" or not os.environ.get("DISPLAY"):
            args.append("--headless=new")

        log.info("launching system browser: %s (port %d)", binary, port)
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not await _wait_cdp(port):
            log.warning("browser did not expose CDP in time, falling back to chromium")
            self._stop_proc()
            return None

        pw = await async_playwright().start()
        self._playwright = pw
        cdp = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        # у браузера с user-data-dir уже есть дефолтный контекст — используем его
        context = cdp.contexts[0] if cdp.contexts else await cdp.new_context(
            locale="ru-RU", timezone_id="Europe/Moscow",
            viewport={"width": 1440, "height": 900},
        )
        context.set_default_timeout(30_000)
        log.info("connected to system browser over CDP")
        return context

    async def _start_chromium(self) -> BrowserContext:
        pw = await async_playwright().start()
        self._playwright = pw
        profile = PROFILE_DIR / "chromium"
        profile.mkdir(parents=True, exist_ok=True)
        context = await pw.chromium.launch_persistent_context(
            str(profile),
            headless=True,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context.set_default_timeout(30_000)
        return context

    def _stop_proc(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None

    async def context(self) -> BrowserContext:
        async with self._lock:
            if self._context is None:
                self._context = (await self._start_system_browser()) or (await self._start_chromium())
            return self._context

    async def new_page(self) -> Page:
        context = await self.context()
        page = await context.new_page()
        await page.add_init_script(_STEALTH_JS)
        return page

    async def close(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
        self._stop_proc()
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None


browser = AvitoBrowser()


async def page_delay() -> None:
    """Щадящая случайная пауза между открытием страниц объявлений."""
    lo, hi = sorted((settings.page_delay_min, settings.page_delay_max))
    await asyncio.sleep(random.uniform(lo, hi))


async def goto(page: Page, url: str, retries: int = 2) -> None:
    """Открывает URL, при 429 ждёт и пробует ещё раз, проверяет страницу блокировки."""
    for attempt in range(retries + 1):
        resp = await page.goto(url, wait_until="domcontentloaded")
        if resp is not None and resp.status == 429 and attempt < retries:
            log.warning("HTTP 429 on %s, retry in 15s (attempt %d)", url, attempt + 1)
            await asyncio.sleep(15)
            continue
        if resp is not None and resp.status in (403, 429):
            raise BlockedError(f"Avito вернул HTTP {resp.status} — похоже, сработал лимит. "
                               "Подождите несколько минут и попробуйте снова.")
        body = (await page.content()).lower()
        for marker in _BLOCK_MARKERS:
            if marker in body:
                raise BlockedError("Avito показал страницу блокировки/капчи. "
                                   "Подождите несколько минут, уменьшите число объявлений или задайте "
                                   "бóльшие паузы в .env (PAGE_DELAY_MIN/MAX).")
        title = await page.title()
        log.debug("opened %s -> %s", url, title)
        return
