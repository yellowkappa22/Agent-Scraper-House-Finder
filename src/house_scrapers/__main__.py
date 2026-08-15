from __future__ import annotations

import argparse
from collections.abc import Sequence

SCRAPERS = ("dailyinfo", "finders", "onthemarket", "spareroom")
COMMANDS = (*SCRAPERS, "enrich-bike", "filter-results", "pipeline", "refresh-all")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="house-scrapers")
    parser.add_argument("scraper", nargs="?", choices=COMMANDS)
    parser.add_argument("--list", action="store_true", help="list available scrapers")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(SCRAPERS))
        return 0
    if args.scraper is None:
        parser.error("a scraper name is required (or use --list)")
    if args.scraper == "dailyinfo":
        from house_scrapers.scrapers.dailyinfo import run
        run()
    elif args.scraper == "finders":
        from house_scrapers.scrapers.finders import run
        run()
    elif args.scraper == "onthemarket":
        from house_scrapers.scrapers.onthemarket import run
        run()
    elif args.scraper == "spareroom":
        from house_scrapers.scrapers.spareroom import run
        run()
    elif args.scraper == "enrich-bike":
        from house_scrapers.enrichment import run
        run()
    elif args.scraper == "pipeline":
        from house_scrapers.pipeline import run
        run()
    elif args.scraper == "filter-results":
        from house_scrapers.filtering import run
        run()
    elif args.scraper == "refresh-all":
        from house_scrapers.pipeline import run_full
        run_full()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
