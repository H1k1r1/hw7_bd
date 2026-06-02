import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from kafka import KafkaProducer
import json

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_ERRORS = Counter(
    "http_request_errors_total", "Total HTTP errors", ["method", "endpoint", "error_type"]
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

app = FastAPI(title="API Service")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/appdb")
KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


def get_db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_kafka_producer():
    try:
        return KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            request_timeout_ms=5000
        )
    except Exception:
        return None


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
        status = str(response.status_code)
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status=status).inc()
        if response.status_code >= 400:
            REQUEST_ERRORS.labels(method=request.method, endpoint=request.url.path, error_type=status).inc()
        return response
    except Exception as exc:
        REQUEST_ERRORS.labels(method=request.method, endpoint=request.url.path, error_type="500").inc()
        raise exc
    finally:
        REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(time.time() - start)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-service"}


class ProductCreate(BaseModel):
    name: str
    stock: int


class OrderCreate(BaseModel):
    product_id: int
    quantity: int


@app.post("/api/products", status_code=201)
def create_product(payload: ProductCreate):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO products (name, stock) VALUES (%s, %s) RETURNING *",
                (payload.name, payload.stock)
            )
            product = dict(cur.fetchone())
            conn.commit()
        return product
    finally:
        conn.close()


@app.get("/api/products/{product_id}")
def get_product(product_id: int):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            product = cur.fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
        return dict(product)
    finally:
        conn.close()


@app.post("/api/orders", status_code=201)
def create_order(payload: OrderCreate):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id = %s FOR UPDATE", (payload.product_id,))
            product = cur.fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            if product["stock"] < payload.quantity:
                raise HTTPException(status_code=400, detail="Insufficient stock")
            cur.execute(
                "INSERT INTO orders (product_id, quantity, status) VALUES (%s, %s, 'confirmed') RETURNING *",
                (payload.product_id, payload.quantity)
            )
            order = dict(cur.fetchone())
            cur.execute("UPDATE products SET stock = stock - %s WHERE id = %s",
                        (payload.quantity, payload.product_id))
            cur.execute(
                "INSERT INTO stock_reservations (product_id, order_id, reserved_quantity) VALUES (%s, %s, %s)",
                (payload.product_id, order["id"], payload.quantity)
            )
            conn.commit()
        producer = get_kafka_producer()
        if producer:
            producer.send("orders", {"order_id": order["id"], "status": "confirmed"})
            producer.flush()
        return order
    finally:
        conn.close()


@app.get("/api/orders/{order_id}")
def get_order(order_id: int):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
        return dict(order)
    finally:
        conn.close()
