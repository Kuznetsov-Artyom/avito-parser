"""Тесты скоринга и гео-логики."""

from __future__ import annotations

from app.geo import haversine_km
from app.models import Listing, SearchRequest, Seller
from app.scoring import NEUTRAL, price_scores, reliability_score, score_all


def _listing(**seller_kwargs) -> Listing:
    return Listing(
        avito_id="1", title="t", price=1000, url="https://www.avito.ru/1",
        seller=Seller(**seller_kwargs),
    )


REQ = SearchRequest(query="test", city="moskva",
                    user_lat=55.7558, user_lng=37.6173,
                    weight_reliability=0.4, weight_price=0.3, weight_distance=0.3)


# ---------- надёжность ----------

def test_reliability_no_data_is_neutral():
    assert reliability_score(_listing()) == NEUTRAL


def test_reliability_perfect_seller():
    from datetime import date
    year = date.today().year - 10  # аккаунту 10 лет
    l = _listing(rating=5.0, reviews=200, member_since=year,
                 badges=["Документы проверены", "Авито Доставка"])
    assert reliability_score(l) > 90


def test_reliability_rating_dominates():
    good = _listing(rating=5.0, reviews=1)
    bad = _listing(rating=1.0, reviews=1)
    assert reliability_score(good) > reliability_score(bad)


def test_reliability_more_reviews_better():
    few = _listing(rating=4.0, reviews=2)
    many = _listing(rating=4.0, reviews=100)
    assert reliability_score(many) > reliability_score(few)


# ---------- цена ----------

def test_price_scores_cheapest_is_best():
    listings = [
        Listing(avito_id="a", price=100),
        Listing(avito_id="b", price=500),
        Listing(avito_id="c", price=1000),
        Listing(avito_id="d", price=None),  # без цены
    ]
    scores = price_scores(listings)
    assert scores[0] == 100.0
    assert scores[2] == 0.0
    assert scores[3] == NEUTRAL  # без цены — нейтрально


def test_price_scores_single_priced():
    scores = price_scores([Listing(avito_id="a", price=100)])
    assert scores == [NEUTRAL]


# ---------- удалённость ----------

def test_distance_score_within_radius():
    l = _listing()
    l.lat, l.lng = 55.7558, 37.6173  # та же точка, что у пользователя
    from app.scoring import distance_score
    assert distance_score(l, REQ, 50) == 100.0


def test_distance_score_far_away_zero():
    l = _listing()
    l.lat, l.lng = 59.9375, 30.3086  # СПб ~ 700 км от Москвы
    from app.scoring import distance_score
    assert distance_score(l, REQ, 50) == 0.0


def test_distance_score_no_coords_neutral():
    from app.scoring import distance_score
    assert distance_score(_listing(), REQ, 50) == NEUTRAL


# ---------- итоговый балл ----------

def test_total_is_weighted_average():
    listings = [
        Listing(avito_id="a", price=100),
        Listing(avito_id="b", price=1000),
    ]
    scores = score_all(listings, REQ, 50)
    # без данных о продавце и координатах: rel=50, dist=50; цена даёт разброс
    for s, expected_price in zip(scores, [100.0, 0.0]):
        expected_total = (0.4 * 50 + 0.3 * expected_price + 0.3 * 50) / 1.0
        assert abs(s.total - expected_total) < 0.2


def test_total_respects_zero_weights():
    req = SearchRequest(query="t", city="moskva",
                        weight_reliability=1.0, weight_price=0.0, weight_distance=0.0)
    listings = [
        Listing(avito_id="a", price=100),
        Listing(avito_id="b", price=1000),
    ]
    scores = score_all(listings, req, 50)
    # только надёжность (нейтральная) — баллы равны
    assert scores[0].total == scores[1].total == 50.0


# ---------- гео ----------

def test_haversine_moscow_to_spb():
    d = haversine_km(55.7558, 37.6173, 59.9375, 30.3086)
    assert 630 < d < 720


def test_haversine_zero():
    assert haversine_km(55.0, 37.0, 55.0, 37.0) == 0.0


def test_search_url():
    from app.parser.urls import build_search_url
    url = build_search_url("iphone 15", "moskva", 50000, 120000)
    assert url.startswith("https://www.avito.ru/moskva?q=")
    assert "pmin=50000" in url and "pmax=120000" in url


# ---------- города ----------

def test_match_city_slug_exact():
    from app.parser.urls import match_city_slug
    assert match_city_slug("Москва") == "moskva"
    assert match_city_slug("  екатеринбург ") == "ekaterinburg"
    assert match_city_slug("Ростов-на-Дону") == "rostov-na-donu"


def test_match_city_slug_fuzzy_and_none():
    from app.parser.urls import match_city_slug
    assert match_city_slug("город Казань") == "kazan"      # приставка слева
    assert match_city_slug("Тверью") == "tver" or match_city_slug("Тверью") is None  # любой исход ок
    assert match_city_slug(None) is None
    assert match_city_slug("Нью-Йорк") is None


def test_russia_in_city_list():
    from app.parser.urls import CITY_SUGGESTIONS, match_city_slug
    slugs = [s for s, _ in CITY_SUGGESTIONS]
    assert "rossiya" in slugs
    assert match_city_slug("Вся Россия") == "rossiya"
