# AviaWatch

Мониторинг цен на авиабилеты: собирает цены с разных сайтов и показывает их в Telegram-боте, а владельцу даёт веб-админку с мониторингом и конфигуратором источников.

Статус: **этап 1 (фундамент)**. Источники, поиск, фильтры, история цен, CLI-проверка. Бот и админка будут на следующих этапах.

## Быстрый старт (локально, без Docker)

```bash
cp .env.example .env          # заполнить TRAVELPAYOUTS_TOKEN
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\alembic upgrade head
```

Проверить источник:

```bash
.venv\Scripts\python -m sources.check --list
.venv\Scripts\python -m sources.check aviasales_api HRG MOW 2026-11-20 --to 2026-11-25 --adults 2
```

Тесты: `.venv\Scripts\python -m pytest`

## Инфраструктура в Docker

```bash
docker compose up -d postgres redis prometheus node-exporter
docker compose run --rm migrate
```

## Структура

```
backend/
  common/     конфиг, БД, модели, метрики
  sources/    источники цен (по файлу на сайт), registry, CLI check
  search/     оркестратор, runner (таймауты/ретраи/прокси/rate limit), фильтры, склейка дублей, кэш
  migrations/ Alembic
  tests/      тесты на сохранённых ответах сайтов (fixtures/)
infra/        конфиги Prometheus
```

### Как добавить новый источник

1. Создать `backend/sources/<name>.py` с классом-наследником `Source` и декоратором `@register`. Метод `search(query, ctx)` возвращает список `FlightOffer`.
2. Добавить импорт в `sources/registry.py::_load_builtin`.
3. Сохранить реальный ответ сайта в `tests/fixtures/` и написать тест парсинга.
4. Проверить вживую: `python -m sources.check <name> ...`.

При следующем поиске конфиг источника сам появится в БД (`source_configs`). Там же включение, прокси, лимиты и таймауты.
