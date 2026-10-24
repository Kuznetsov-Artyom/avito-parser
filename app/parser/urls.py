"""Построение URL поиска Avito: https://www.avito.ru/{город}?q=...&pmin=...&pmax=..."""

from __future__ import annotations

from urllib.parse import quote_plus

BASE = "https://www.avito.ru"

# Города для выпадающего списка (slug = часть URL на avito.ru).
# Первый элемент «Вся Россия» — поиск по всей стране.
CITY_SUGGESTIONS = [
    ("rossiya", "Вся Россия"),
    ("moskva", "Москва"),
    ("sankt_peterburg", "Санкт-Петербург"),
    ("novosibirsk", "Новосибирск"),
    ("ekaterinburg", "Екатеринбург"),
    ("kazan", "Казань"),
    ("nizhniy_novgorod", "Нижний Новгород"),
    ("chelyabinsk", "Челябинск"),
    ("samara", "Самара"),
    ("omsk", "Омск"),
    ("rostov-na-donu", "Ростов-на-Дону"),
    ("ufa", "Уфа"),
    ("krasnoyarsk", "Красноярск"),
    ("voronezh", "Воронеж"),
    ("perm", "Пермь"),
    ("volgograd", "Волгоград"),
    ("krasnodar", "Краснодар"),
    ("saratov", "Саратов"),
    ("tyumen", "Тюмень"),
    ("tolyatti", "Тольятти"),
    ("ulyanovsk", "Ульяновск"),
    ("barnaul", "Барнаул"),
    ("izhevsk", "Ижевск"),
    ("irkutsk", "Иркутск"),
    ("habarovsk", "Хабаровск"),
    ("yaroslavl", "Ярославль"),
    ("vladivostok", "Владивосток"),
    ("mahachkala", "Махачкала"),
    ("tomsk", "Томск"),
    ("orenburg", "Оренбург"),
    ("kemerovo", "Кемерово"),
    ("novokuznetsk", "Новокузнецк"),
    ("ryazan", "Рязань"),
    ("astrahan", "Астрахань"),
    ("naberezhnye_chelny", "Набережные Челны"),
    ("penza", "Пенза"),
    ("lipetsk", "Липецк"),
    ("kirov", "Киров"),
    ("cheboksary", "Чебоксары"),
    ("balashiha", "Балашиха"),
    ("kaliningrad", "Калининград"),
    ("kursk", "Курск"),
    ("sochi", "Сочи"),
    ("stavropol", "Ставрополь"),
    ("tver", "Тверь"),
    ("magnitogorsk", "Магнитогорск"),
    ("bryansk", "Брянск"),
    ("belgorod", "Белгород"),
    ("vladimir", "Владимир"),
    ("arhangelsk", "Архангельск"),
    ("ulan_ude", "Улан-Удэ"),
]

# нормализованное имя -> slug («москва» -> «moskva»)
CITY_MAP = {name.lower(): slug for slug, name in CITY_SUGGESTIONS}


def match_city_slug(city_name: str | None) -> str | None:
    """Ищет slug города по русскому названию (например, из геокодирования).

    Понимает точное совпадение, приставки («город Казань») и простые падежи
    («Тверью» → «Тверь»). Возвращает None, если города нет в списке.
    """
    if not city_name:
        return None
    key = city_name.strip().lower().replace("ё", "е")
    if key in CITY_MAP:
        return CITY_MAP[key]
    padded = f" {key} "
    for name, slug in CITY_MAP.items():
        # имя города целиком внутри строки («город казань» → «казань»)
        if f" {name} " in padded:
            return slug
        # падёж/приставка: имя с началом как у ключа или наоборот
        if name.startswith(key) or key.startswith(name):
            return slug
    return None


def city_slug(city: str) -> str:
    """Приводит город к slug: убирает пробелы/дефисы, переводит в латиницу если нужно.

    Ожидается, что фронтенд присылает уже готовый slug (select), но на всякий случай
    нормализуем.
    """
    slug = city.strip().lower().replace(" ", "_").replace("-", "_")
    return slug


def build_search_url(query: str, city: str, price_min: int | None, price_max: int | None) -> str:
    parts = [f"q={quote_plus(query.strip())}"]
    if price_min is not None and price_min > 0:
        parts.append(f"pmin={price_min}")
    if price_max is not None and price_max > 0:
        parts.append(f"pmax={price_max}")
    return f"{BASE}/{city_slug(city)}?{'&'.join(parts)}"


def build_item_url(path: str) -> str:
    """Абсолютный URL объявления из относительного href."""
    if path.startswith("http"):
        return path
    return BASE + path
