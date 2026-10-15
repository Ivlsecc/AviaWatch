# AviaWatch

Мониторинг цен на авиабилеты: собирает цены с разных сайтов и показывает их в Telegram-боте, а владельцу даёт веб-админку с мониторингом и конфигуратором источников.

Статус: этапы 1–3 готовы (поиск, бот, история и рекомендации), идёт этап 4 — подключение источников.

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

## Источники

| Источник | Статус | Как устроен |
|---|---|---|
| `aviasales_api` | ✅ работает | Официальный Travelpayouts Data API. Одна минимальная цена на день, цены из кэша. Используется в основном для календаря и средней цены |
| `tutu` | ✅ работает | Собственные JSON API Туту без капчи: `offers-api.tutu.ru/avia/offers/v2`, календарь, подсказки. Полные маршруты с сегментами, багажом и раздельными билетами |
| Aviasales, живой поиск | ⏳ нужен браузер | `tickets-api.aviasales.ru/search/v2/start` закрыт AWS WAF (CloudFront 403 на прямые запросы). Возможен только через Playwright |
| Т-Путешествия | ⏳ нужно решение | Сертификат сайта выдан «Russian Trusted Root CA» (Минцифры), которого нет в стандартных хранилищах. Нужно добавить этот корневой сертификат в доверенные для этого источника |
| Яндекс Путешествия | ❌ не подходит | Сразу показывает SmartCaptcha. Капчи не обходим |
| OneTwoTrip | ⏳ не исследован | По прямой ссылке открывается пустая страница поиска |
| Чартеры, авиакомпании | ⏳ не исследованы | |

### Как добавить новый источник

1. Создать `backend/sources/<name>.py` с классом-наследником `Source` и декоратором `@register`. Метод `search(query, ctx)` возвращает список `FlightOffer`.
2. Добавить импорт в `sources/registry.py::_load_builtin`.
3. Сохранить реальный ответ сайта в `tests/fixtures/` и написать тест парсинга.
4. Проверить вживую: `python -m sources.check <name> ...`.

При следующем поиске конфиг источника сам появится в БД (`source_configs`). Там же включение, прокси, лимиты и таймауты.
