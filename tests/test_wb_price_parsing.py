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
    ("url", "expected_curr"),
    [
        ("https://www.wildberries.by/catalog/604645219/detail.aspx?size=822662730", "byn"),
        ("https://www.wildberries.ru/catalog/604645219/detail.aspx", "rub"),
        (None, "rub"),
    ],
)
def test_build_wb_v4_params_selects_currency_by_domain(url: str | None, expected_curr: str) -> None:
    params = _build_wb_v4_params("604645219", url)
    assert params["nm"] == "604645219"
    assert params["curr"] == expected_curr


@pytest.mark.parametrize(
    ("product", "size_option_id", "expected_price"),
    [
        ({"salePriceU": 175800}, None, 1758),
        (
            {
                "sizes": [
                    {"optionId": 111, "price": {"product": 120500}},
                    {"optionId": 822662730, "price": {"product": 6680}},
                ]
            },
            822662730,
            66,
        ),
        (
            {
                "sizes": [
                    {"optionId": 111, "price": {"product": 120500}},
                    {"optionId": 222, "price": {"basic": 99500}},
                ]
            },
            None,
            995,
        ),
    ],
)
def test_extract_price_from_wb_product(product: dict, size_option_id: int | None, expected_price: int) -> None:
    assert _extract_price_from_wb_product(product, size_option_id) == expected_price
