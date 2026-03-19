"""
LINE Messaging API push module.
Sends Flex Message digests to LINE group and individual users.

Strategy:
- Score 4-5: Flex Message carousel (rich cards with deep analysis)
- Score 2-3: Text message list (title + PubMed link + deep analysis button)
"""

import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message"


class LinePusher:
    """Send messages via LINE Messaging API."""

    def __init__(self):
        self.channel_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.group_id = os.environ.get("LINE_GROUP_ID", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.channel_token and self.group_id)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_token}",
        }

    def push_to_group(self, message: dict) -> bool:
        """Push a message to the configured LINE group."""
        if not self.is_configured:
            logger.warning("LINE not configured - skipping push")
            return False
        return self._push(self.group_id, message)

    def push_to_group_multi(self, messages: list[dict]) -> bool:
        """Push multiple messages in one API call (max 5)."""
        if not self.is_configured:
            logger.warning("LINE not configured - skipping push")
            return False
        # LINE allows max 5 messages per push
        for i in range(0, len(messages), 5):
            batch = messages[i:i+5]
            payload = {
                "to": self.group_id,
                "messages": batch,
            }
            try:
                resp = requests.post(
                    f"{LINE_API_URL}/push",
                    headers=self._headers(),
                    json=payload,
                    timeout=30,
                )
                if resp.status_code == 200:
                    logger.info(f"LINE push sent ({len(batch)} messages)")
                else:
                    logger.error(f"LINE push failed: {resp.status_code} {resp.text}")
                    return False
            except Exception as e:
                logger.error(f"LINE push error: {e}")
                return False
        return True

    def push_to_user(self, user_id: str, message: dict) -> bool:
        """Push a message to a specific user (for on-demand responses)."""
        if not self.channel_token:
            logger.warning("LINE not configured - skipping push")
            return False
        return self._push(user_id, message)

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
        Build and send the daily digest to LINE group.
        - Score 4-5 + on-demand: Flex Message carousel (rich cards)
        - Score 2-3: Text message with title list + links
        """
        from .line_flex_builder import build_digest_flex

        on_demand = on_demand or []
        high = [a for a in articles if a.get("total_score", 0) >= 4]
        medium = [a for a in articles if 2 <= a.get("total_score", 0) <= 3]

        if not high and not medium and not on_demand:
            logger.info("No articles to send to LINE")
            return False

        messages = []

        # Message 1: Flex carousel for Score 4-5 + on-demand
        if high or on_demand:
            flex_message = build_digest_flex(high, on_demand)
            if flex_message:
                messages.append(flex_message)

        # Message 2: Compact Flex for Score 2-3 (with feedback buttons)
        if medium:
            from .line_flex_builder import build_compact_list_flex
            compact = build_compact_list_flex(medium, len(high), len(on_demand))
            if compact:
                messages.append(compact)

        # Fallback if only medium articles
        if not high and not on_demand and medium:
            from .line_flex_builder import build_compact_list_flex
            compact = build_compact_list_flex(medium, 0, 0)
            if compact:
                messages = [compact]

        return self.push_to_group_multi(messages)

    def _build_medium_text(self, articles: list[dict], high_count: int = 0, on_demand_count: int = 0) -> str:
        """Build text message for Score 2-3 articles with daily stats."""
        total = len(articles) + high_count + on_demand_count
        header = f"NICU Journal Digest\n"
        header += f"Today: {total} articles total"
        if high_count:
            header += f" · {high_count} deep analysis ↑"
        header += f"\n\n━━━ Score 2-3: {len(articles)} articles ━━━\n"
        return header + self._build_medium_text_body(articles)

    def _build_medium_text_body(self, articles: list[dict]) -> str:
        """Build the body of the text list."""
        lines = []
        for i, a in enumerate(articles, 1):
            score = a.get("total_score", 0)
            pmid = a.get("pmid", "")
            title = a.get("title", "")[:80]
            journal = a.get("source_journal", "")
            one_liner = a.get("one_liner", "")

            line = f"\n[{score}] {title}"
            if len(a.get("title", "")) > 80:
                line += "..."
            line += f"\n    {journal}"
            if one_liner:
                line += f"\n    → {one_liner[:60]}"
            line += f"\n    pubmed.ncbi.nlm.nih.gov/{pmid}/"

            lines.append(line)

        # Max LINE text message = 5000 chars
        text = "\n".join(lines)
        if len(text) > 4800:
            text = text[:4800] + "\n\n... (more articles in email/web)"
        return text

    def send_instant_alert(self, article: dict):
        """Send immediate alert for Score 5 articles."""
        from .line_flex_builder import build_single_article_flex

        flex = build_single_article_flex(article)
        if not flex:
            return False

        alert_msg = {
            "type": "text",
            "text": f"🔔 Must-read alert: Score {article.get('total_score', 5)}\n{article['title'][:60]}...",
        }

        self.push_to_group(alert_msg)
        return self.push_to_group(flex)

    def send_on_demand_result(self, user_id: str, article: dict):
        """Send on-demand deep analysis result to the requesting user."""
        from .line_flex_builder import build_single_article_flex

        flex = build_single_article_flex(article)
        if not flex:
            return False

        notify_msg = {
            "type": "text",
            "text": f"Deep analysis 完成 ✅\n{article['title'][:50]}...",
        }
        self.push_to_user(user_id, notify_msg)
        return self.push_to_user(user_id, flex)
