#!/bin/bash
set -e

PROMETHEUS="http://localhost:9090"
FAILED=0

query() {
  curl -sf "${PROMETHEUS}/api/v1/query" --data-urlencode "query=${1}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); r=d['data']['result']; print(r[0]['value'][1] if r else '0')"
}

ERROR_RATE=$(query 'sum(rate(http_request_errors_total[5m])) / sum(rate(http_requests_total[5m]))')
echo "Error rate: ${ERROR_RATE}"
python3 -c "import sys; sys.exit(0 if float('${ERROR_RATE}') < 0.01 else 1)" || { echo "[FAIL] error rate >= 1%"; FAILED=1; }

P95=$(query 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))')
echo "p95 latency: ${P95}s"
python3 -c "import sys; sys.exit(0 if float('${P95}') < 0.5 else 1)" || { echo "[FAIL] p95 >= 500ms"; FAILED=1; }

UP_COUNT=$(query 'count(up{job=~"api-service|consumer-service"} == 1)')
echo "Services up: ${UP_COUNT}"
python3 -c "import sys; sys.exit(0 if int(float('${UP_COUNT}')) == 2 else 1)" || { echo "[FAIL] not all services up"; FAILED=1; }

[ $FAILED -ne 0 ] && exit 1
echo "All metrics checks passed"
