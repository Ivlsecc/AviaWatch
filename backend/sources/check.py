"""Живая проверка одного источника без БД и бота.

    python -m sources.check aviasales_api HRG MOW 2026-11-20
    python -m sources.check aviasales_api HRG MOW 2026-11-20 --to 2026-11-25 --adults 2
    python -m sources.check --list
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from common.config import get_settings
from search.dedup import merge_duplicates
from search.filters import FilterSettings, apply_filters
from search.runner import RunSettings, SourceRunner
from sources.base import SearchQuery
from sources.registry import all_sources, get_source


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Проверка источника цен")
    p.add_argument("source", nargs="?")
    p.add_argument("origin", nargs="?")
    p.add_argument("destination", nargs="?")
    p.add_argument("date", nargs="?", type=date.fromisoformat)
    p.add_argument("--to", type=date.fromisoformat, help="конец диапазона дат")
    p.add_argument("--adults", type=int, default=1)
    p.add_argument("--direct", action="store_true")
    p.add_argument("--no-filters", action="store_true", help="показать всё без отсева")
    p.add_argument("--proxy")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--list", action="store_true", help="список источников")
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    if args.list:
        for name, cls in sorted(all_sources().items()):
            print(f"{name:20} {cls.method:8} {cls.title}")
        return 0
    if not all([args.source, args.origin, args.destination, args.date]):
        print("Нужно: source origin destination date (или --list)")
        return 2

    settings = get_settings()
    source = get_source(args.source)
    params = {"token": settings.travelpayouts_token, "marker": settings.travelpayouts_marker, "market": "ru"}
    query = SearchQuery(
        origin=args.origin.upper(),
        destination=args.destination.upper(),
        date_from=args.date,
        date_to=args.to or args.date,
        adults=args.adults,
        direct_only=args.direct,
    )

    runner = SourceRunner()
    try:
        res = await runner.run(
            source, query, RunSettings(retries=0, proxy=args.proxy or source.default_proxy or settings.http_proxy or None, params=params)
        )
    finally:
        await runner.close()

    if not res.ok:
        print(f"ОШИБКА [{source.name}] за {res.elapsed_s:.1f}с: {res.error}")
        return 1

    offers = res.offers if args.no_filters else apply_filters(res.offers, FilterSettings())
    offers = merge_duplicates(offers)
    print(f"[{source.name}] {len(res.offers)} предложений, после фильтров {len(offers)}, за {res.elapsed_s:.1f}с\n")
    for o in offers[: args.limit]:
        dur = f"{o.duration_min // 60}ч{o.duration_min % 60:02d}" if o.duration_min else "—"
        when = f"{o.departure_at:%d.%m %H:%M}" if o.time_known else f"{o.departure_at:%d.%m} --:--"
        print(
            f"{o.price_rub:>8} ₽  {when}  {o.origin_airport}→{o.destination_airport}  "
            f"пересадок {o.transfers}  {dur:>6}  {','.join(o.flight_numbers) or ','.join(o.airlines)}"
        )
        print(f"           {o.link}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
