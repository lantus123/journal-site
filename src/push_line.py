"""
LINE Messaging API push module.
Notification + link mode:
- Daily digest: one concise text message with web link
- Score 5: Flex Message instant alert
- On-demand: plain text result to individual user
"""

import os
import logging
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message"
TW_TZ = timezone(timedelta(hours=8))


class LinePusher:
    """Send messages via LINE Messaging API."""

    def __init__(self):
        self.channel_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.group_id = os.environ.get("LINE_GROUP_ID", "")
        self.site_url = os.environ.get(
            "DIGEST_SITE_URL", "https://lantus123.github.io/nicu-journal-site"
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.channel_token and self.group_id)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_token}",
        }

    def _push(self, to: str, message: dict) -> bool:
        """Send a push message."""
        payload = {
            "to": to,
            "messages": [message],
        }
        try:
            resp = requests.post(
                f"{LINE_API_URL}/push",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info(f"LINE push sent to {to[:10]}...")
                return True
            else:
                logger.error(f"LINE push failed: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"LINE push error: {e}")
            return False

    def send_digest(self, articles: list[dict], on_demand: list[dict] = None):
        """
        Send a concise text notification to LINE group with web link.
        """
        if not self.is_configured:
            logger.warning("LINE not configured - skipping push")
            return False

        on_demand = on_demand or []
        high = [a for a in articles if a.get("total_score", 0) >= 4]
        medium = [a for a in articles if 2 <= a.get("total_score", 0) <= 3]

        if not high and not medium and not on_demand:
            logger.info("No articles to send to LINE")
            return False

        today = datetime.now(TW_TZ)
        date_str = today.strftime("%Y-%m-%d")
        display_date = today.strftime("%m/%d (%a)")
        total = len(high) + len(medium) + len(on_demand)
        web_url = f"{self.site_url}/{date_str}.html"

        lines = [
            f"📰 NICU Journal Digest {display_date}",
            f"共 {total} 篇文章",
            "",
        ]

        # Score 4-5 titles
        if high:
            lines.append(f"⭐ Score 4-5: {len(high)} 篇")
            for a in high:
                score = a.get("total_score", 0)
                title = a.get("title", "")[:70]
                if len(a.get("title", "")) > 70:
                    title += "..."
                lines.append(f"  [{score}] {title}")
            lines.append("")

        # Score 2-3 count only
        if medium:
            lines.append(f"📋 Score 2-3: {len(medium)} 篇")
            lines.append("")

        # On-demand
        if on_demand:
            lines.append(f"🔬 同事要求分析: {len(on_demand)} 篇")
            lines.append("")

        lines.append(f"👉 完整內容：{web_url}")

        text = "\n".join(lines)
        message = {"type": "text", "text": text}
        return self._push(self.group_id, message)

    def send_instant_alert(self, article: dict):
        """Send immediate Flex Message alert for Score 5 articles."""
        if not self.is_configured:
            logger.warning("LINE not configured - skipping alert")
            return False

        from .line_flex_builder import build_single_article_flex

        flex = build_single_article_flex(article)
        if not flex:
            return False

        alert_msg = {
            "type": "text",
            "text": f"🔔 Must-read alert: Score {article.get('total_score', 5)}\n{article['title'][:60]}...",
        }

        self._push(self.group_id, alert_msg)
        return self._push(self.group_id, flex)

    def send_on_demand_result(self, user_id: str, article: dict):
        """Send on-demand deep analysis result as plain text."""
        if not self.channel_token:
            logger.warning("LINE not configured - skipping push")
            return False

        deep = article.get("deep_analysis", {})
        lines = [
            "📋 Deep Analysis 完成",
            "━━━━━━━━━━━━━━━━━━━━",
            article.get("title", ""),
            f"{article.get('authors', '')} · {article.get('source_journal', '')}",
            "",
        ]

        thirty = deep.get("thirty_second_summary", "")
        if thirty:
            lines.append(f"🎯 30 秒重點：{thirty}")
            lines.append("")

        meth = deep.get("methodology_audit", {})
        strengths = meth.get("strengths", [])
        weaknesses = meth.get("weaknesses", [])
        if strengths:
            lines.append(f"✅ Strong: {strengths[0]}")
        if weaknesses:
            lines.append(f"⚠️ Weak: {weaknesses[0]}")
        if strengths or weaknesses:
            lines.append("")

        impact = deep.get("protocol_impact", {})
        proposed = impact.get("proposed_change", "")
        if proposed:
            lines.append(f"🏥 對我們科的影響：{proposed}")
            lines.append("")

        pmid = article.get("pmid", "")
        lines.append(f"PubMed: https://pubmed.ncbi.nlm.nih.gov/{pmid}/")

        text = "\n".join(lines)
        # LINE text max 5000 chars
        if len(text) > 4900:
            text = text[:4900] + "\n..."

        message = {"type": "text", "text": text}
        return self._push(user_id, message)
