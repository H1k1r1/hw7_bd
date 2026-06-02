# Домашнее задание №7
## CI/CD, Testing & Observability

## Структура проекта

```text
hw7-cicd/
├── .github/workflows/ci.yml
├── docker-compose.yml
├── README.md
├── api-service/
│   ├── main.py
│   ├── init.sql
│   ├── Dockerfile
│   ├── requirements.txt
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── e2e/
├── consumer-service/
│   ├── main.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── tests/unit/
├── load-tests/
│   └── load_test.js
├── scripts/
│   └── check_metrics.sh
└── monitoring/
    ├── prometheus.yml
    ├── alerts.yml
    ├── alertmanager.yml
    └── grafana/
        ├── provisioning/
        └── dashboards/
```

## Запуск

```bash
docker compose up -d
docker compose ps
```

Доступные интерфейсы:

- API service: `http://localhost:8080`
- Consumer service: `http://localhost:8081`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Alertmanager: `http://localhost:9093`

Логин в Grafana:
- user: `admin`
- password: `admin`

## Kafka

В `docker-compose.yml` Kafka настроена с двумя listener'ами:

- внутренний для контейнеров: `kafka:9092`
- внешний для хоста: `localhost:29092`

## 1. CI pipeline

Файл: `.github/workflows/ci.yml`

Pipeline автоматически запускается при:

- `push`
- `pull_request`

Этапы pipeline:

1. `build` - сборка Docker-образов
2. `unit-tests` - модульные тесты
3. `integration-tests` - интеграционные тесты
4. `e2e-tests` - сквозной сценарий
5. `load-tests` - нагрузочное тестирование и проверка метрик

## 2. Интеграционные тесты

Тесты запускаются одной командой:

```bash
docker compose run --rm api-service pytest tests/integration/ -v
```

## 3. End-to-End тест

E2E тест покрывает полный пользовательский сценарий marketplace:

```bash
docker compose run --rm api-service pytest tests/e2e/ -v
```

## 4. Prometheus и базовые метрики

Оба сервиса экспортируют метрики на endpoint `/metrics`.

Используются следующие базовые метрики:

- `http_requests_total`
- `http_request_errors_total`
- `http_request_duration_seconds`

Cобирает метрики через `scrape_configs`.

## 5. Grafana: дашборды сервисов

Показываются:

- latency: `p50`, `p95`, `p99`
- errors: error rate / error count
- throughput: requests per second

## 6. Grafana: дашборд инфраструктуры

- PostgreSQL - active connections, query rate, cache hit ratio
- Kafka - consumer lag, broker status, message flow

## 7. Нагрузочное тестирование

Для нагрузки используется `k6`.

Параметры:

- минимум `10 VU`
- минимум `30 секунд`

Нагрузочный тест запускается из CI и содержит thresholds.  
Если thresholds нарушены, pipeline падает.

## 8. E2E + нагрузка + метрики в одном CI прогоне

Проверяются условия:

- `error rate < 1%`
- `p95 latency < 500ms`
- сервисы доступны (`up == 1`)

## 9. Alert Rules

Файл: `monitoring/alerts.yml`

Определены alert rules как код минимум для следующих ситуаций:

- высокий error rate;
- высокая latency;
- service down;
- Kafka consumer lag.

Алерты можно продемонстрировать, например, остановив `api-service`:

```bash
docker stop api-service
```

После этого алерт `ServiceDown` перейдёт в состояние `firing`.

## 10. SLI / SLO

В системе определены три SLI:

### SLI 1 - API Availability

Измеряется доля успешных запросов ко всем HTTP-запросам:

PromQL:

```promql
1 - (
  rate(http_request_errors_total[5m])
  /
  rate(http_requests_total[5m])
)
```

- **SLO:** > 99.5%
- **Порог отказа:** < 95%

### SLI 2 - API Latency p95

Измеряется 95-й перцентиль времени ответа API.

PromQL:

```promql
histogram_quantile(
  0.95,
  sum by (le, method, endpoint) (
    rate(http_request_duration_seconds_bucket[5m])
  )
)
```

- **SLO:** < 500ms
- **Порог отказа:** > 1000ms

### SLI 3 - Kafka Consumer Lag

Измеряется задержка обработки сообщений consumer-сервисом.

PromQL:

```promql
sum(kafka_consumergroup_lag) by (consumergroup, topic)
```

- **SLO:** < 100
- **Порог отказа:** > 1000

## Использование SLI

`scripts/check_metrics.sh`

## Команды для запуска и проверок

Поднять систему:

```bash
docker compose up -d
```

Показать статус контейнеров:

```bash
docker compose ps
```

Запустить unit tests:

```bash
docker compose run --rm api-service pytest tests/unit/ -v
docker compose run --rm consumer-service pytest tests/unit/ -v
```

Запустить integration tests:

```bash
docker compose run --rm api-service pytest tests/integration/ -v
```

Запустить E2E:

```bash
docker compose run --rm api-service pytest tests/e2e/ -v
```

Запустить нагрузку:

```bash
docker run --rm `
  --network hw7_fix_default `
  -e BASE_URL=http://api-service:8080 `
  -v ${PWD}/load-tests:/scripts `
  grafana/k6 run /scripts/load_test.js
```

Проверить метрики:

```bash
bash scripts/check_metrics.sh
```
