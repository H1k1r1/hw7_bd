import pytest


def parse_order_message(message: dict) -> dict:
    for field in ["order_id", "status"]:
        if field not in message:
            raise ValueError(f"Missing required field: {field}")
    return {"order_id": message["order_id"], "status": message["status"]}


def test_parse_valid_message():
    result = parse_order_message({"order_id": 42, "status": "confirmed"})
    assert result["order_id"] == 42
    assert result["status"] == "confirmed"


def test_parse_missing_order_id():
    with pytest.raises(ValueError, match="order_id"):
        parse_order_message({"status": "confirmed"})


def test_parse_missing_status():
    with pytest.raises(ValueError, match="status"):
        parse_order_message({"order_id": 1})


def test_all_valid_statuses():
    for s in ["confirmed", "shipped", "cancelled"]:
        result = parse_order_message({"order_id": 1, "status": s})
        assert result["status"] == s
