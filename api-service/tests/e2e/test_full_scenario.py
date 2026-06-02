import os
import time
import pytest
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

API_BASE = os.getenv("API_BASE_URL", "http://api-service:8080")
CONSUMER_BASE = os.getenv("CONSUMER_BASE_URL", "http://consumer-service:8081")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/appdb")


@pytest.fixture(scope="module", autouse=True)
def wait_for_services():
    for url in [f"{API_BASE}/health", f"{CONSUMER_BASE}/health"]:
        for _ in range(30):
            try:
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            pytest.fail(f"Service not ready: {url}")


@pytest.fixture(scope="module")
def db_conn():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    yield conn
    conn.close()


def test_e2e_marketplace_order_flow(db_conn):
    product_resp = requests.post(f"{API_BASE}/api/products",
                                 json={"name": "E2E Test Product", "stock": 100})
    assert product_resp.status_code == 201
    product = product_resp.json()
    product_id = product["id"]

    order_resp = requests.post(f"{API_BASE}/api/orders",
                               json={"product_id": product_id, "quantity": 15})
    assert order_resp.status_code == 201
    order = order_resp.json()
    assert order["status"] == "confirmed"
    order_id = order["id"]

    product_check = requests.get(f"{API_BASE}/api/products/{product_id}")
    assert product_check.json()["stock"] == 85

    with db_conn.cursor() as cur:
        cur.execute("SELECT stock FROM products WHERE id = %s", (product_id,))
        assert cur.fetchone()["stock"] == 85

    with db_conn.cursor() as cur:
        cur.execute("SELECT reserved_quantity FROM stock_reservations WHERE order_id = %s", (order_id,))
        assert cur.fetchone()["reserved_quantity"] == 15

    with db_conn.cursor() as cur:
        cur.execute("SELECT status FROM orders WHERE id = %s", (order_id,))
        assert cur.fetchone()["status"] == "confirmed"

    deadline = time.time() + 60
    consumer_saw_event = False
    while time.time() < deadline:
        r = requests.get(f"{CONSUMER_BASE}/api/processed-orders", timeout=3)
        if r.status_code == 200 and order_id in r.json().get("order_ids", []):
            consumer_saw_event = True
            break
        time.sleep(2)
    assert consumer_saw_event, f"order_id {order_id} not propagated through Kafka to consumer-service within 60s"

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM stock_reservations WHERE order_id = %s", (order_id,))
        cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        db_conn.commit()


def test_e2e_metrics_endpoints():
    for base in [API_BASE, CONSUMER_BASE]:
        resp = requests.get(f"{base}/metrics")
        assert resp.status_code == 200
        assert "http_requests_total" in resp.text
        assert "http_request_duration_seconds" in resp.text
