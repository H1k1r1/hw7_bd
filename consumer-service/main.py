import os
import time
import json
import threading
from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from kafka import KafkaConsumer

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_ERRORS = Counter(
    "http_request_errors_total", "Total HTTP errors", ["method", "endpoint", "error_type"]
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)
KAFKA_MESSAGES_CONSUMED = Counter(
    "kafka_messages_consumed_total", "Kafka messages consumed", ["topic", "status"]
)

app = FastAPI(title="Consumer Service")

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
processed_orders = {}


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
    return {"status": "ok", "service": "consumer-service"}


@app.get("/api/processed-orders")
def get_processed_orders():
    return {"processed": len(processed_orders), "order_ids": list(processed_orders.keys())}


def kafka_consumer_loop():
    while True:
        try:
            consumer = KafkaConsumer(
                "orders",
                bootstrap_servers=KAFKA_SERVERS,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                group_id="consumer-service",
                auto_offset_reset="earliest",
            )
        except Exception:
            time.sleep(2)
            continue

        try:
            for message in consumer:
                try:
                    data = message.value
                    processed_orders[data.get("order_id")] = data.get("status")
                    KAFKA_MESSAGES_CONSUMED.labels(topic="orders", status="success").inc()
                except Exception:
                    KAFKA_MESSAGES_CONSUMED.labels(topic="orders", status="error").inc()
        except Exception:
            time.sleep(2)


threading.Thread(target=kafka_consumer_loop, daemon=True).start()
