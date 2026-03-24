#!/usr/bin/env python3
"""
Backfill a missing web digest for a specific date.

Reads PMIDs from knowledge_base.json for the given date,
re-fetches from PubMed, re-scores with AI, and generates
the web digest HTML.

Usage:
  python scripts/backfill_digest.py 2026-03-22

Requires env vars: ANTHROPIC_API_KEY, NCBI_API_KEY
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

import yaml
from src.fetcher import PubMedFetcher
from src.fulltext import FulltextFetcher
from src.scorer import ArticleScorer
from src.llm import LLMClient
from src.web_digest import WebDigestGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")

TW_TZ = timezone(timedelta(hours=8))


def main():
    parser = argparse.ArgumentParser(description="Backfill a missing web digest")
    parser.add_argument("date", help="Date to backfill (YYYY-MM-DD)")
    args = parser.parse_args()

    target_date = args.date

    # Validate date format
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Invalid date format: {target_date}. Use YYYY-MM-DD")
        sys.exit(1)

    display_date = dt.strftime("%Y/%m/%d (%A)")

    # 1. Find PMIDs from knowledge_base
    kb_path = Path("data/knowledge_base.json")
    if not kb_path.exists():
        logger.error("knowledge_base.json not found")
        sys.exit(1)

    with open(kb_path) as f:
        kb = json.load(f)

    target_entries = [e for e in kb if e.get("processed_date") == target_date]
    if not target_entries:
        logger.error(f"No entries found for {target_date} in knowledge_base.json")
        sys.exit(1)

    pmids = [e["pmid"] for e in target_entries]
    logger.info(f"Found {len(pmids)} articles for {target_date}: {pmids}")

    # 2. Re-fetch from PubMed
    with open("config/journals.yaml") as f:
        journals_config = yaml.safe_load(f)

    fetcher = PubMedFetcher(journals_config)
    articles = fetcher.fetch_details(pmids)
    logger.info(f"Fetched {len(articles)} articles from PubMed")

    if not articles:
        logger.error("Could not fetch articles from PubMed")
        sys.exit(1)

    # 3. Check OA
    ft_fetcher = FulltextFetcher()
    articles = ft_fetcher.enrich_articles(articles)

    # 4. Score with AI
    with open("config/scoring_config.yaml") as f:
        scoring_config = yaml.safe_load(f)

    llm = LLMClient()
    scorer = ArticleScorer(llm, scoring_config)
    articles = scorer.process_all(articles)

    for a in articles:
        logger.info(f"  [{a.get('total_score', '?')}] {a['title'][:70]}")

    # 5. Generate web digest with the target date
    digest_articles = [a for a in articles if a.get("total_score", 0) >= 2]
    if not digest_articles:
        logger.error("No articles scored >= 2, nothing to generate")
        sys.exit(1)

    web = WebDigestGenerator()
    web.generate(digest_articles, [], override_date=target_date)
    logger.info(f"Web digest generated for {target_date}")

    # 6. Show usage
    usage = llm.get_usage_summary()
    logger.info(f"LLM usage: {json.dumps(usage)}")


if __name__ == "__main__":
    main()
