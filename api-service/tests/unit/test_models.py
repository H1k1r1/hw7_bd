import pytest


def calculate_new_stock(current: int, reserved: int) -> int:
    if reserved > current:
        raise ValueError("Insufficient stock")
    return current - reserved


def test_stock_calculation_success():
    assert calculate_new_stock(100, 10) == 90


def test_stock_calculation_zero():
    assert calculate_new_stock(10, 10) == 0


def test_stock_calculation_insufficient():
    with pytest.raises(ValueError, match="Insufficient stock"):
        calculate_new_stock(5, 10)


def test_order_status_transitions():
    valid_transitions = {"pending": ["confirmed", "cancelled"], "confirmed": ["shipped", "cancelled"]}
    assert "confirmed" in valid_transitions["pending"]
    assert "shipped" in valid_transitions["confirmed"]
    assert "shipped" not in valid_transitions["pending"]


def test_product_name_validation():
    def validate_name(name: str) -> bool:
        return bool(name and 1 <= len(name) <= 255)
    assert validate_name("Valid Product") is True
    assert validate_name("") is False
    assert validate_name("A" * 256) is False
