"""
Feedback collection and processing.
Handles feedback from LINE postback and Email URL tracking.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))


def _feedback_path(dept: str = "newborn") -> Path:
    return Path(f"data/{dept}/feedback.json")


def load_feedback(dept: str = "newborn") -> list[dict]:
    """Load existing feedback data."""
    path = _feedback_path(dept)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_feedback(feedback: list[dict], dept: str = "newborn"):
    """Save feedback data."""
    path = _feedback_path(dept)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(feedback, f, ensure_ascii=False, indent=2)


def add_feedback(pmid: str, rating: str, source: str = "line", user_id: str = "anonymous", dept: str = "newborn"):
    """
    Add a single feedback entry.

    Args:
        pmid: PubMed ID of the article
        rating: must_read | useful | so_so | skip | not_relevant
        source: line | email
        user_id: LINE user ID or email tracking ID (anonymized)
        dept: department ID
    """
    feedback = load_feedback(dept)

    entry = {
        "pmid": pmid,
        "rating": rating,
        "source": source,
        "user_id": user_id,
        "timestamp": datetime.now(TW_TZ).isoformat(),
    }

    # Check for duplicate (same user, same article)
    for i, existing in enumerate(feedback):
        if existing["pmid"] == pmid and existing["user_id"] == user_id:
            feedback[i] = entry  # Update existing vote
            logger.info(f"Updated feedback: PMID {pmid} = {rating} (by {user_id[:8]}...)")
            save_feedback(feedback, dept)
            return entry

    feedback.append(entry)
    logger.info(f"New feedback: PMID {pmid} = {rating} (by {user_id[:8]}...)")
    save_feedback(feedback, dept)
    return entry


def add_on_demand_request(pmid: str, user_id: str, dept: str = "newborn"):
    """
    Add an on-demand deep analysis request to the queue.
    The GAS webhook calls this (via API), and main.py picks it up next day.
    """
    queue_path = Path(f"data/{dept}/on_demand_queue.json")
    queue = []
    if queue_path.exists():
        with open(queue_path) as f:
            queue = json.load(f)

    # Avoid duplicates
    if any(r["pmid"] == pmid for r in queue):
        logger.info(f"On-demand already queued: PMID {pmid}")
        return

    queue.append({
        "pmid": pmid,
        "user_id": user_id,
        "timestamp": datetime.now(TW_TZ).isoformat(),
    })

    with open(queue_path, "w") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    logger.info(f"On-demand queued: PMID {pmid} (requested by {user_id[:8]}...)")


def get_feedback_summary(pmid: str, dept: str = "newborn") -> dict:
    """Get aggregated feedback for an article."""
    feedback = load_feedback(dept)
    article_fb = [f for f in feedback if f["pmid"] == pmid]

    if not article_fb:
        return {"total": 0, "ratings": {}}

    ratings = {}
    for f in article_fb:
        r = f["rating"]
        ratings[r] = ratings.get(r, 0) + 1

    return {
        "total": len(article_fb),
        "ratings": ratings,
    }


RATING_SCORES = {
    "must_read": 1.0,
    "useful": 0.5,
    "so_so": 0.0,
    "skip": -0.5,
    "not_relevant": -1.0,
}


def compute_topic_boost(dept: str = "newborn") -> dict[str, float]:
    """
    從醫師回饋自動計算 topic_boost。
    邏輯：將回饋 rating 轉為數值，按 keyword 彙總平均分，
    只有正向且 >= 3 筆回饋的 keyword 才產生 boost (0.1~0.5)。
    """
    feedback = load_feedback(dept)
    if not feedback:
        logger.info("No feedback data - topic_boost unchanged")
        return {}

    # 讀取 knowledge base 取得 PMID → keywords 對應
    kb_path = Path(f"data/{dept}/knowledge_base.json")
    if not kb_path.exists():
        logger.info("No knowledge base - topic_boost unchanged")
        return {}

    with open(kb_path) as f:
        kb = json.load(f)

    pmid_keywords = {entry["pmid"]: entry.get("keywords", []) for entry in kb}

    # 彙總每個 keyword 的回饋分數
    keyword_scores: dict[str, list[float]] = {}
    for fb in feedback:
        score = RATING_SCORES.get(fb["rating"])
        if score is None:
            continue
        keywords = pmid_keywords.get(fb["pmid"], [])
        for kw in keywords:
            kw_lower = kw.lower()
            keyword_scores.setdefault(kw_lower, []).append(score)

    # 計算 boost：正向 + 至少 3 筆回饋
    MIN_FEEDBACK_COUNT = 3
    MAX_BOOST = 0.5
    topic_boost = {}
    for kw, scores in keyword_scores.items():
        if len(scores) < MIN_FEEDBACK_COUNT:
            continue
        avg = sum(scores) / len(scores)
        if avg <= 0:
            continue
        # 映射到 0.1 ~ 0.5
        boost = round(min(avg * 0.5, MAX_BOOST), 2)
        boost = max(boost, 0.1)
        topic_boost[kw] = boost

    if topic_boost:
        logger.info(f"Topic boost from feedback: {topic_boost}")
    else:
        logger.info("No keyword qualified for topic boost (need >= 3 positive feedback)")

    return topic_boost


def parse_line_postback(postback_data: str) -> dict:
    """
    Parse LINE postback data string into a dict.
    Example: "action=feedback&pmid=12345678&rating=must_read"
    """
    params = {}
    for pair in postback_data.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = value
    return params
