"""Расчёт баллов: надёжность продавца, цена, удалённость, итоговый балл.

Все баллы нормированы в 0..100. Итог — средневзвешенная сумма с весами из запроса.
"""

from __future__ import annotations

import math
from datetime import date

from .geo import haversine_km
from .models import Listing, Scores, SearchRequest

NEUTRAL = 50.0  # нейтральный балл, когда данных нет

# Сколько «стоит» каждый компонент надёжности (сумма = 100)
_RATING_WEIGHT = 40
_REVIEWS_WEIGHT = 30
_AGE_WEIGHT = 20
_BADGES_WEIGHT = 10

# Бейджи, которые реально говорят о надёжности (остальным верим меньше)
_TRUSTED_BADGES = {
    "документы проверены",
    "авито доставка",
    "проверенный продавец",
    "магазин проверен авито",
    "товар проверен авито",
    "реквизиты проверены",
    "данные подтверждены",
    "надёжный продавец",
}


def reliability_score(listing: Listing) -> float:
    """Балл надёжности продавца 0..100.

    - рейтинг (0..5) -> до 40
    - число отзывов (лог. шкала, 100 отзывов ≈ максимум) -> до 30
    - возраст аккаунта («на Avito с ...», до 5 лет) -> до 20
    - бейджи -> до 10
    Если данных нет совсем — нейтральные 50.
    """
    seller = listing.seller
    has_any = (
        seller.rating is not None
        or seller.reviews
        or seller.member_since
        or bool(seller.badges)
    )
    if not has_any:
        return NEUTRAL

    score = 0.0
    parts = 0.0  # суммарный вес задействованных компонентов

    if seller.rating is not None and seller.rating > 0:
        score += _RATING_WEIGHT * min(seller.rating / 5.0, 1.0)
        parts += _RATING_WEIGHT

    if seller.reviews and seller.reviews > 0:
        # 1 отзыв ~ 15 баллов из 30, 10 отзывов ~ 25, 100+ -> максимум
        score += _REVIEWS_WEIGHT * min(math.log10(seller.reviews + 1) / 2.0, 1.0)
        parts += _REVIEWS_WEIGHT

    if seller.member_since:
        age = max(date.today().year - seller.member_since, 0)
        score += _AGE_WEIGHT * min(age / 5.0, 1.0)
        parts += _AGE_WEIGHT

    if seller.badges:
        trusted = sum(1 for b in seller.badges if b.strip().lower() in _TRUSTED_BADGES)
        score += _BADGES_WEIGHT * min(trusted / 2.0, 1.0)
        parts += _BADGES_WEIGHT

    # если часть компонентов неизвестна, масштабируем то, что известно, до 0..100
    return min(100.0, score / parts * 100) if parts else NEUTRAL


def price_scores(listings: list[Listing]) -> list[float]:
    """Балл цены 0..100: перцентильный ранг внутри выдачи (дешевле = выше).

    Объявления без цены получают нейтральный балл.
    """
    result = [NEUTRAL] * len(listings)
    priced = [(i, l.price) for i, l in enumerate(listings) if l.price is not None and l.price > 0]
    if len(priced) < 2:
        return result

    priced.sort(key=lambda x: x[1])
    n = len(priced)
    for rank, (idx, _price) in enumerate(priced):
        # самый дешёвый (rank=0) -> 100, самый дорогой (rank=n-1) -> ~0
        result[idx] = 100.0 * (1.0 - rank / (n - 1))
    return result


def distance_score(listing: Listing, req: SearchRequest, radius_km: float) -> float:
    """Балл удалённости 0..100: в пределах радиуса — почти 100, дальше — падает до 0.

    Нет координат у объявления или у пользователя — нейтральные 50.
    """
    if req.user_lat is None or req.user_lng is None or listing.lat is None or listing.lng is None:
        return NEUTRAL
    dist = haversine_km(req.user_lat, req.user_lng, listing.lat, listing.lng)
    if dist <= radius_km * 0.1:  # прямо рядом — полный балл
        return 100.0
    return max(0.0, 100.0 * (1.0 - dist / radius_km))


def score_all(listings: list[Listing], req: SearchRequest, radius_km: float) -> list[Scores]:
    """Считает все баллы для списка объявлений."""
    w_rel = req.weight_reliability
    w_price = req.weight_price
    w_dist = req.weight_distance
    w_sum = w_rel + w_price + w_dist
    if w_sum <= 0:
        w_rel, w_price, w_dist, w_sum = 1.0, 1.0, 1.0, 3.0

    prices = price_scores(listings)
    out: list[Scores] = []
    for listing, price_score in zip(listings, prices):
        rel = reliability_score(listing)
        dist = distance_score(listing, req, radius_km)
        total = (w_rel * rel + w_price * price_score + w_dist * dist) / w_sum
        out.append(Scores(reliability=round(rel, 1), price=round(price_score, 1),
                          distance=round(dist, 1), total=round(total, 1)))
    return out
