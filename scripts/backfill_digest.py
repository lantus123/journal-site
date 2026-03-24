#!/usr/bin/env python3
"""
Backfill a missing web digest for a specific date.

Reads articles from knowledge_base.json for the given date,
re-fetches details from PubMed, and generates the web digest HTML
using existing scores (no AI re-scoring needed).

Usage:
  python scripts/backfill_digest.py 2026-03-22
  python scripts/backfill_digest.py 2026-03-22 2026-03-23   # multiple dates

Requires env vars: NCBI_API_KEY (optional but recommended)
Optional: DIGEST_PASSWORD, FEEDBACK_WEBHOOK_URL, FEEDBACK_SECRET
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetcher import PubMedFetcher
from src.web_digest import WebDigestGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


def backfill_date(target_date: str, kb: list[dict], fetcher: PubMedFetcher):
    """Backfill a single date's digest."""
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Invalid date format: {target_date}. Use YYYY-MM-DD")
        return False

    # Find entries for this date
    target_entries = [e for e in kb if e.get("processed_date") == target_date]
    if not target_entries:
        logger.error(f"No entries found for {target_date} in knowledge_base.json")
        return False

    pmids = [e["pmid"] for e in target_entries]
    logger.info(f"Found {len(pmids)} articles for {target_date}: {pmids}")

    # Build a lookup from knowledge_base scores
    kb_lookup = {e["pmid"]: e for e in target_entries}

    # Fetch article details from PubMed
    articles = fetcher.fetch_details(pmids)
    logger.info(f"Fetched {len(articles)} articles from PubMed")

    if not articles:
        logger.error("Could not fetch articles from PubMed")
        return False

    # Merge knowledge_base scores into fetched articles (skip AI re-scoring)
    for a in articles:
        pmid = a["pmid"]
        if pmid in kb_lookup:
            entry = kb_lookup[pmid]
            a["total_score"] = entry.get("total_score", 0)
            a["scores"] = entry.get("scores", {})
            a["one_liner"] = entry.get("one_liner", "")
            a["keywords"] = entry.get("keywords", [])
            # Build minimal summary from one_liner
            if entry.get("one_liner"):
                a["summary"] = {"significance": entry["one_liner"]}

    for a in articles:
        logger.info(f"  [{a.get('total_score', '?')}] {a['title'][:70]}")

    # Generate web digest
    digest_articles = [a for a in articles if a.get("total_score", 0) >= 2]
    if not digest_articles:
        logger.warning(f"No articles scored >= 2 for {target_date}, skipping")
        return False

    web = WebDigestGenerator()
    web.generate(digest_articles, [], override_date=target_date)
    logger.info(f"Web digest generated for {target_date}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Backfill missing web digests")
    parser.add_argument("dates", nargs="+", help="Dates to backfill (YYYY-MM-DD)")
    args = parser.parse_args()

    # Load knowledge base
    kb_path = Path("data/knowledge_base.json")
    if not kb_path.exists():
        logger.error("knowledge_base.json not found")
        sys.exit(1)

    with open(kb_path) as f:
        kb = json.load(f)

    # Initialize PubMed fetcher
    import yaml
    with open("config/journals.yaml") as f:
        journals_config = yaml.safe_load(f)
    fetcher = PubMedFetcher(journals_config)

    # Backfill each date
    success = 0
    for date in args.dates:
        if backfill_date(date, kb, fetcher):
            success += 1

    logger.info(f"Backfill complete: {success}/{len(args.dates)} dates processed")


if __name__ == "__main__":
    main()
