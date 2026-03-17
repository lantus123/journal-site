#!/usr/bin/env python3
"""
NICU/PICU Journal Auto-Review System
Main entry point for daily pipeline.

Usage:
  python main.py                    # Full daily run
  python main.py --dry-run          # Fetch + score, don't send email
  python main.py --test-email       # Send test email with sample data
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Taiwan timezone
TW_TZ = timezone(timedelta(hours=8))


def load_config() -> tuple[dict, dict]:
    """Load journal and scoring configs."""
    with open("config/journals.yaml") as f:
        journals_config = yaml.safe_load(f)
    with open("config/scoring_config.yaml") as f:
        scoring_config = yaml.safe_load(f)
    return journals_config, scoring_config


def load_on_demand_queue() -> list[dict]:
    """Load and clear on-demand analysis queue from yesterday."""
    queue_path = Path("data/on_demand_queue.json")
    if not queue_path.exists():
        return []
    with open(queue_path) as f:
        queue = json.load(f)
    # Clear queue after reading
    with open(queue_path, "w") as f:
        json.dump([], f)
    return queue


def save_to_knowledge_base(articles: list[dict]):
    """Append processed articles to knowledge base."""
    kb_path = Path("data/knowledge_base.json")
    kb = []
    if kb_path.exists():
        with open(kb_path) as f:
            kb = json.load(f)

    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    for article in articles:
        kb_entry = {
            "pmid": article["pmid"],
            "title": article["title"],
            "journal": article.get("source_journal", ""),
            "pub_date": article.get("pub_date", ""),
            "total_score": article.get("total_score", 0),
            "scores": article.get("scores", {}),
            "keywords": article.get("keywords", []),
            "one_liner": article.get("one_liner", ""),
            "processed_date": today,
            "has_deep_analysis": "deep_analysis" in article,
        }
        kb.append(kb_entry)

    with open(kb_path, "w") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    logger.info(f"Knowledge base updated: {len(kb)} total entries")


def run_pipeline(dry_run: bool = False):
    """Execute the full daily pipeline."""
    from src.fetcher import PubMedFetcher
    from src.fulltext import FulltextFetcher
    from src.scorer import ArticleScorer
    from src.llm import LLMClient
    from src.push_email import EmailPusher

    logger.info("=" * 60)
    logger.info("NICU/PICU Journal Auto-Review System")
    logger.info(f"Run time: {datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')} (Taiwan)")
    logger.info("=" * 60)

    # 1. Load configs
    journals_config, scoring_config = load_config()
    logger.info(f"Tracking {len(journals_config.get('journals', []))} journals")

    # 2. Fetch new articles from PubMed
    logger.info("\n--- Phase 1: Fetching articles ---")
    fetcher = PubMedFetcher(journals_config)
    articles = fetcher.fetch_new_articles()

    if not articles:
        logger.info("No new articles found. Exiting.")
        fetcher.save_cache()
        return

    # 3. Check OA availability
    logger.info("\n--- Phase 2: Checking OA availability ---")
    ft_fetcher = FulltextFetcher()
    articles = ft_fetcher.enrich_articles(articles)

    # 4. Score with Haiku + Deep analyze with Sonnet
    logger.info("\n--- Phase 3: AI Scoring & Analysis ---")
    llm = LLMClient()
    scorer = ArticleScorer(llm, scoring_config)
    articles = scorer.process_all(articles)

    # 5. Report results
    logger.info("\n--- Results ---")
    score_dist = {}
    for a in articles:
        s = a.get("total_score", 0)
        score_dist[s] = score_dist.get(s, 0) + 1
    logger.info(f"Score distribution: {json.dumps(score_dist, sort_keys=True)}")

    deep_count = sum(1 for a in articles if "deep_analysis" in a)
    logger.info(f"Deep analyses performed: {deep_count}")

    # Log usage
    usage = llm.get_usage_summary()
    logger.info(f"LLM usage: {json.dumps(usage)}")

    # 6. Save to knowledge base
    save_to_knowledge_base(articles)

    # 7. Save PMID cache
    fetcher.save_cache()

    # 8. Send digest (Email + LINE)
    if not dry_run:
        logger.info("\n--- Phase 4: Sending digest ---")
        on_demand = load_on_demand_queue()
        if on_demand:
            logger.info(f"Including {len(on_demand)} on-demand analyses from yesterday")

        digest_articles = [a for a in articles if a.get("total_score", 0) >= 2]

        # Email
        emailer = EmailPusher()
        email_ok = emailer.send_digest(digest_articles, on_demand)
        if email_ok:
            logger.info("Email digest sent!")
        else:
            logger.warning("Email not sent (not configured or failed)")

        # LINE
        from src.push_line import LinePusher
        line = LinePusher()
        if line.is_configured:
            line_ok = line.send_digest(digest_articles, on_demand)
            if line_ok:
                logger.info("LINE digest sent!")
            else:
                logger.error("LINE digest failed")

            # Instant alert for Score 5
            score5 = [a for a in articles if a.get("total_score", 0) >= 5]
            for a in score5:
                line.send_instant_alert(a)
                logger.info(f"LINE instant alert sent for PMID {a['pmid']}")
        else:
            logger.warning("LINE not configured - skipping")
    else:
        logger.info("\n[DRY RUN] Skipping push")
        for a in articles[:3]:
            logger.info(
                f"  [{a.get('total_score', '?')}] {a['title'][:70]}..."
            )

    logger.info("\n--- Done ---")


def test_email():
    """Send a test email with sample data."""
    from src.push_email import EmailPusher

    sample = [
        {
            "pmid": "99999999",
            "title": "Test Article: Early Caffeine in VLBW Infants",
            "authors": "Test A, Test B, et al.",
            "source_journal": "JAMA Pediatrics",
            "pub_date": "2026 Mar",
            "doi": "10.1001/test.2026",
            "total_score": 5,
            "scores": {"design": 5, "relevance": 5, "novelty": 4, "generalizability": 5},
            "summary": {
                "purpose": "評估 VLBW 早產兒早期 caffeine 對 BPD 的影響",
                "design": "多中心 RCT，12 中心，n=1,847",
                "findings": "BPD 發生率 18.2% vs 25.3%（RR 0.72, p<0.001），NNT=8",
                "significance": "為早期高劑量 caffeine 方案提供高等級證據",
            },
            "one_liner": "近十年最重要的 caffeine RCT，直接影響 NICU 常規照護",
            "keywords": ["caffeine", "BPD", "VLBW", "RCT"],
            "is_oa": True,
            "oa_url": "https://example.com/fulltext",
        }
    ]

    emailer = EmailPusher()
    success = emailer.send_digest(sample)
    if success:
        logger.info("Test email sent!")
    else:
        logger.error("Test email failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NICU/PICU Journal Auto-Review System")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending emails")
    parser.add_argument("--test-email", action="store_true", help="Send test email")
    args = parser.parse_args()

    if args.test_email:
        test_email()
    else:
        run_pipeline(dry_run=args.dry_run)
