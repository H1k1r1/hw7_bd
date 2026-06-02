import os
import time
import pytest
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/appdb")
API_BASE = os.getenv("API_BASE_URL", "http://api-service:8080")
CONSUMER_BASE = os.getenv("CONSUMER_BASE_URL", "http://consumer-service:8081")


@pytest.fixture(autouse=True)
def cleanup_db():
    yield
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM stock_reservations")
        cur.execute("DELETE FROM orders")
        cur.execute("DELETE FROM products WHERE name LIKE 'TEST_%'")
        conn.commit()
    conn.close()


def test_create_product_persists_to_db():
    resp = requests.post(f"{API_BASE}/api/products", json={"name": "TEST_Widget", "stock": 50})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "TEST_Widget"
    assert data["stock"] == 50

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = %s", (data["id"],))
        row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row["stock"] == 50


def test_create_order_reserves_stock():
    product_resp = requests.post(f"{API_BASE}/api/products", json={"name": "TEST_Item", "stock": 100})
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    order_resp = requests.post(f"{API_BASE}/api/orders", json={"product_id": product_id, "quantity": 20})
    assert order_resp.status_code == 201
    assert order_resp.json()["status"] == "confirmed"

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT stock FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        cur.execute("SELECT reserved_quantity FROM stock_reservations WHERE order_id = %s",
                    (order_resp.json()["id"],))
        reservation = cur.fetchone()
    conn.close()
    assert product["stock"] == 80
    assert reservation["reserved_quantity"] == 20


def test_order_fails_on_insufficient_stock():
    product_resp = requests.post(f"{API_BASE}/api/products", json={"name": "TEST_Limited", "stock": 5})
    product_id = product_resp.json()["id"]
    resp = requests.post(f"{API_BASE}/api/orders", json={"product_id": product_id, "quantity": 10})
    assert resp.status_code == 400


def test_order_fails_on_nonexistent_product():
    resp = requests.post(f"{API_BASE}/api/orders", json={"product_id": 999999, "quantity": 1})
    assert resp.status_code == 404


def test_order_event_propagates_to_consumer_via_kafka():
    product_resp = requests.post(f"{API_BASE}/api/products", json={"name": "TEST_KafkaFlow", "stock": 50})
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    order_resp = requests.post(f"{API_BASE}/api/orders", json={"product_id": product_id, "quantity": 3})
    assert order_resp.status_code == 201
    order_id = order_resp.json()["id"]

    deadline = time.time() + 60
    found = False
    while time.time() < deadline:
        r = requests.get(f"{CONSUMER_BASE}/api/processed-orders", timeout=3)
        if r.status_code == 200 and order_id in r.json().get("order_ids", []):
            found = True
            break
        time.sleep(2)
    assert found, f"order_id {order_id} not seen by consumer-service within 60s"
