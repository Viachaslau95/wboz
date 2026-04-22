from decimal import Decimal

import pytest

from bot.marketplaces import (
    _build_wb_v4_params,
    _extract_price_from_wb_product,
    _extract_wb_size_option_id,
)


def test_extract_wb_size_option_id_from_url() -> None:
    url = "https://www.wildberries.by/catalog/604645219/detail.aspx?size=822662730"
    assert _extract_wb_size_option_id(url) == 822662730


@pytest.mark.parametrize(
    ("url", "expected_curr", "expected_dest"),
    [
        ("https://www.wildberries.by/catalog/604645219/detail.aspx?size=822662730", "byn", "507"),
        ("https://www.wildberries.ru/catalog/604645219/detail.aspx", "rub", "-1257786"),
        (None, "rub", "-1257786"),
    ],
)
def test_build_wb_v4_params_selects_currency_by_domain(
    url: str | None,
    expected_curr: str,
    expected_dest: str,
) -> None:
    params = _build_wb_v4_params("604645219", url)
    assert params["nm"] == "604645219"
    assert params["curr"] == expected_curr
    assert params["dest"] == expected_dest


@pytest.mark.parametrize(
    ("product", "size_option_id", "expected_price"),
    [
        ({"salePriceU": 175800}, None, Decimal("1758.00")),
        (
            {
                "sizes": [
                    {"optionId": 111, "price": {"product": 120500}},
                    {"optionId": 822662730, "price": {"product": 6680}},
                ]
            },
            822662730,
            Decimal("66.80"),
        ),
        (
            {
                "sizes": [
                    {"optionId": 111, "price": {"product": 120500}},
                    {"optionId": 222, "price": {"basic": 99500}},
                ]
            },
            None,
            Decimal("995.00"),
        ),
    ],
)
def test_extract_price_from_wb_product(
    product: dict,
    size_option_id: int | None,
    expected_price: Decimal,
) -> None:
    assert _extract_price_from_wb_product(product, size_option_id) == expected_price


def test_size_in_url_uses_variants_price_not_top_level_sale() -> None:
    """С ?size= цена с уровня товара (salePriceU) — часто не тот размер; брать с sizes[].optionId."""
    product = {
        "salePriceU": 9691,
        "sizes": [
            {"optionId": 1056352700, "price": {"product": 10494}},
        ],
    }
    assert _extract_price_from_wb_product(product, 1056352700) == Decimal("104.94")


def test_size_in_url_string_option_id_matches() -> None:
    by_url = "https://www.wildberries.by/catalog/604645219/detail.aspx?size=822662730"
    product = {
        "salePriceU": 10000,
        "sizes": [
            {"optionId": "822662730", "price": {"product": 6680}},
        ],
    }
    assert _extract_price_from_wb_product(product, 822662730, url=by_url) == Decimal("66.80")


def test_byn_no_size_uses_min_rank_size_not_min_sale() -> None:
    """Без ?size= salePriceU на карточке — часто глобальный минимум, на сайте цена у дефолтного размера (rank)."""
    by_url = "https://www.wildberries.by/catalog/1/detail.aspx"
    product = {
        "salePriceU": 5550,
        "sizes": [
            {
                "optionId": 1,
                "rank": 200000,
                "price": {"product": 5864, "logistics": 0, "return": 0, "basic": 7000},
            },
            {
                "optionId": 2,
                "rank": 300000,
                "price": {"product": 5550, "logistics": 0, "return": 0, "basic": 8000},
            },
        ],
    }
    assert _extract_price_from_wb_product(product, None, url=by_url) == Decimal("58.64")


def test_byn_vitrine_subtracts_logistics_from_v4_product() -> None:
    by_url = "https://www.wildberries.by/catalog/739959261/detail.aspx?size=1056352700"
    product = {
        "sizes": [
            {
                "optionId": 1056352700,
                "price": {"basic": 15502, "product": 10890, "logistics": 478, "return": 0},
            },
        ],
    }
    assert _extract_price_from_wb_product(product, 1056352700, url=by_url) == Decimal("104.94")
