#!/usr/bin/env python3
"""
Backfill a missing web digest for a specific date.

Two modes:
  - Default: uses existing scores/summaries from knowledge_base.json (no API key needed)
  - --full:  re-fetches from PubMed, re-scores with AI (requires ANTHROPIC_API_KEY)

Usage:
  python scripts/backfill_digest.py 2026-03-22
  python scripts/backfill_digest.py 2026-03-22 2026-03-23
  python scripts/backfill_digest.py 2026-03-22 --full   # full AI re-scoring

Requires env vars: NCBI_API_KEY (optional but recommended)
For --full mode: ANTHROPIC_API_KEY
Optional: DIGEST_PASSWORD, FEEDBACK_WEBHOOK_URL, FEEDBACK_SECRET
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from src.fetcher import PubMedFetcher
from src.web_digest import WebDigestGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


def backfill_date(target_date: str, kb: list[dict], fetcher: PubMedFetcher, full: bool):
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

    if full:
        return _backfill_full(target_date, pmids, fetcher)
    else:
        return _backfill_from_kb(target_date, target_entries, fetcher)


def _backfill_from_kb(target_date: str, kb_entries: list[dict], fetcher: PubMedFetcher) -> bool:
    """Backfill using existing knowledge_base data + PubMed details."""
    pmids = [e["pmid"] for e in kb_entries]
    kb_lookup = {e["pmid"]: e for e in kb_entries}

    # Fetch article details from PubMed (for authors, etc.)
    articles = fetcher.fetch_details(pmids)
    logger.info(f"Fetched {len(articles)} articles from PubMed")

    if not articles:
        logger.error("Could not fetch articles from PubMed")
        return False

    # Merge knowledge_base data into fetched articles
    for a in articles:
        pmid = a["pmid"]
        if pmid in kb_lookup:
            entry = kb_lookup[pmid]
            a["total_score"] = entry.get("total_score", 0)
            a["scores"] = entry.get("scores", {})
            a["one_liner"] = entry.get("one_liner", "")
            a["keywords"] = entry.get("keywords", [])
            a["source_journal"] = entry.get("journal", a.get("source_journal", ""))

            # Use full summary/deep_analysis if available in KB
            if entry.get("summary"):
                a["summary"] = entry["summary"]
            elif entry.get("one_liner"):
                a["summary"] = {"significance": entry["one_liner"]}

            if entry.get("deep_analysis"):
                a["deep_analysis"] = entry["deep_analysis"]

            if entry.get("is_oa"):
                a["is_oa"] = entry["is_oa"]
            if entry.get("oa_url"):
                a["oa_url"] = entry["oa_url"]
            if entry.get("doi"):
                a["doi"] = entry.get("doi", a.get("doi", ""))

    for a in articles:
        logger.info(f"  [{a.get('total_score', '?')}] {a['title'][:70]}")

    return _generate_digest(target_date, articles)


def _backfill_full(target_date: str, pmids: list[str], fetcher: PubMedFetcher) -> bool:
    """Backfill with full AI re-scoring."""
    from src.fulltext import FulltextFetcher
    from src.scorer import ArticleScorer
    from src.llm import LLMClient

    articles = fetcher.fetch_details(pmids)
    logger.info(f"Fetched {len(articles)} articles from PubMed")

    if not articles:
        logger.error("Could not fetch articles from PubMed")
        return False

    # OA check
    ft_fetcher = FulltextFetcher()
    articles = ft_fetcher.enrich_articles(articles)

    # AI scoring
    with open("config/scoring_config.yaml") as f:
        scoring_config = yaml.safe_load(f)

    llm = LLMClient()
    scorer = ArticleScorer(llm, scoring_config)
    articles = scorer.process_all(articles)

    for a in articles:
        logger.info(f"  [{a.get('total_score', '?')}] {a['title'][:70]}")

    usage = llm.get_usage_summary()
    logger.info(f"LLM usage: {json.dumps(usage)}")

    return _generate_digest(target_date, articles)


def _generate_digest(target_date: str, articles: list[dict]) -> bool:
    """Generate web digest HTML from scored articles."""
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
    parser.add_argument("--full", action="store_true",
                        help="Full AI re-scoring (requires ANTHROPIC_API_KEY)")
    args = parser.parse_args()

    # Load knowledge base
    kb_path = Path("data/knowledge_base.json")
    if not kb_path.exists():
        logger.error("knowledge_base.json not found")
        sys.exit(1)

    with open(kb_path) as f:
        kb = json.load(f)

    # Initialize PubMed fetcher
    with open("config/journals.yaml") as f:
        journals_config = yaml.safe_load(f)
    fetcher = PubMedFetcher(journals_config)

    # Backfill each date
    success = 0
    for date in args.dates:
        if backfill_date(date, kb, fetcher, full=args.full):
            success += 1

    logger.info(f"Backfill complete: {success}/{len(args.dates)} dates processed")


if __name__ == "__main__":
    main()
