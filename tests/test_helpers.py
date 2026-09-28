import pytest
import tricount as tapi

from tricount_flow.config import ConfigError, extract_token
from tricount_flow.core import resolve_category


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://tricount.com/tABC123", "tABC123"),
        ("http://tricount.com/tABC123", "tABC123"),
        ("tricount.com/tABC123", "tABC123"),
        ("https://tricount.com/tABC123/", "tABC123"),
        ("https://tricount.com/tABC123?utm=x", "tABC123"),
        ("tABC123", "tABC123"),
    ],
)
def test_extract_token(link, expected):
    assert extract_token(link) == expected


def test_extract_token_empty():
    with pytest.raises(ConfigError):
        extract_token("   ")


def test_resolve_category_known_enum_name():
    cat, custom = resolve_category("FOOD_AND_DRINK")
    assert cat is tapi.Category.FOOD_AND_DRINK
    assert custom is None


def test_resolve_category_alias_case_insensitive():
    cat, custom = resolve_category("Food")
    assert cat is tapi.Category.FOOD_AND_DRINK
    assert custom is None


def test_resolve_category_custom_label():
    cat, custom = resolve_category("Babysitter")
    assert cat is None
    assert custom == "Babysitter"


def test_resolve_category_none():
    assert resolve_category(None) == (None, None)
