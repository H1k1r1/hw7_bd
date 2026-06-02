import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('error_rate');
const orderDuration = new Trend('order_duration');

export const options = {
  stages: [
    { duration: '10s', target: 5 },
    { duration: '20s', target: 10 },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
    error_rate: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://api-service:8080";

export function setup() {
  const res = http.post(
    `${BASE_URL}/api/products`,
    JSON.stringify({ name: 'LoadTest Product', stock: 100000 }),
    { headers: { 'Content-Type': 'application/json' } }
  );
  return { productId: res.json('id') };
}

export default function (data) {
  const productId = data.productId;

  const healthRes = http.get(`${BASE_URL}/health`);
  check(healthRes, { 'health ok': (r) => r.status === 200 });

  const start = Date.now();
  const orderRes = http.post(
    `${BASE_URL}/api/orders`,
    JSON.stringify({ product_id: productId, quantity: 1 }),
    { headers: { 'Content-Type': 'application/json' } }
  );
  const ok = check(orderRes, {
    'order created': (r) => r.status === 201,
    'status confirmed': (r) => r.json('status') === 'confirmed',
  });
  errorRate.add(!ok);
  orderDuration.add(Date.now() - start);

  const productRes = http.get(`${BASE_URL}/api/products/${productId}`);
  check(productRes, { 'product found': (r) => r.status === 200 });

  sleep(1);
}
