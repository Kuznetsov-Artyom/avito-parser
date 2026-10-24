"""Pydantic-модели: запрос поиска, объявление, продавец, баллы."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """POST /api/search"""

    query: str = Field(min_length=1, max_length=200, description="Поисковый запрос, например: iphone 15")
    city: str = Field(default="moskva", description="Slug города Avito (moskva, sankt_peterburg, ...)")
    price_min: Optional[int] = Field(default=None, ge=0)
    price_max: Optional[int] = Field(default=None, ge=0)
    max_items: int = Field(default=20, ge=1, le=50, description="Сколько объявлений парсить подробно")
    user_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    user_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    user_location: Optional[str] = Field(default=None, max_length=200, description="Текст геопозиции (город/адрес)")
    weight_reliability: float = Field(default=0.4, ge=0, le=1)
    weight_price: float = Field(default=0.3, ge=0, le=1)
    weight_distance: float = Field(default=0.3, ge=0, le=1)


class Seller(BaseModel):
    name: Optional[str] = None
    rating: Optional[float] = None          # 0..5
    reviews: Optional[int] = None           # количество отзывов
    member_since: Optional[int] = None      # год регистрации на Avito
    badges: list[str] = Field(default_factory=list)  # «Документы проверены», «Авито Доставка» и т.п.


class Listing(BaseModel):
    """Одно объявление (результат парсинга)."""

    avito_id: str
    title: str = ""
    price: Optional[int] = None
    url: str = ""
    image_url: Optional[str] = None
    location_text: Optional[str] = None     # «Москва, м. Тверская»
    lat: Optional[float] = None
    lng: Optional[float] = None
    description: Optional[str] = None
    seller: Seller = Field(default_factory=Seller)


class Scores(BaseModel):
    reliability: float = 0.0    # 0..100
    price: float = 0.0          # 0..100
    distance: float = 0.0       # 0..100
    total: float = 0.0          # 0..100


class ScoredListing(BaseModel):
    """Объявление с посчитанными баллами — то, что уходит на фронтенд."""

    avito_id: str
    title: str = ""
    price: Optional[int] = None
    url: str = ""
    image_url: Optional[str] = None
    location_text: Optional[str] = None
    distance_km: Optional[float] = None
    description: Optional[str] = None
    seller: Seller = Field(default_factory=Seller)
    scores: Scores = Field(default_factory=Scores)


class SearchStatus(BaseModel):
    """GET /api/search/{id}"""

    id: str
    status: str                      # pending | running | done | error
    total: int = 0                   # сколько объявлений нашли на странице поиска
    processed: int = 0               # сколько уже обработали подробно
    current_step: Optional[str] = None
    error: Optional[str] = None
    results: list[ScoredListing] = Field(default_factory=list)
