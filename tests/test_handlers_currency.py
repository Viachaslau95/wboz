import pytest

from bot.handlers import _currency_code_by_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.wildberries.by/catalog/604645219/detail.aspx", "BYN"),
        ("https://www.wildberries.ru/catalog/12345678/detail.aspx", "RUB"),
        ("https://www.ozon.ru/product/something-123/", "RUB"),
    ],
)
def test_currency_code_by_url(url: str, expected: str) -> None:
    assert _currency_code_by_url(url) == expected
