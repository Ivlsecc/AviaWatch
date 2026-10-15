"""Метрики Prometheus. Админка читает их через HTTP API Prometheus."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

SOURCE_REQUESTS = Counter("aw_source_requests_total", "Запросы к источникам", ["source", "status"])
SOURCE_LATENCY = Histogram(
    "aw_source_latency_seconds",
    "Время ответа источника",
    ["source"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 15, 30, 60),
)
SOURCE_OFFERS = Counter("aw_source_offers_total", "Найдено предложений", ["source"])
SOURCE_UP = Gauge("aw_source_up", "1 — источник работает, 0 — выключен circuit breaker'ом", ["source"])
SEARCHES = Counter("aw_searches_total", "Поиски", ["origin", "cached"])
NOTIFICATIONS = Counter("aw_notifications_total", "Отправленные уведомления", ["kind"])


def start_metrics_server(port: int) -> None:
    if port:
        start_http_server(port)
