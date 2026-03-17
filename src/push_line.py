"""
LINE Messaging API push module.
Sends Flex Message digests to LINE group and individual users.
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
        """Build and send the daily digest to LINE group."""
        from .line_flex_builder import build_digest_flex

        on_demand = on_demand or []
        digest_articles = [a for a in articles if a.get("total_score", 0) >= 2]

        if not digest_articles and not on_demand:
            logger.info("No articles to send to LINE")
            return False

        flex_message = build_digest_flex(digest_articles, on_demand)
        return self.push_to_group(flex_message)

    def send_instant_alert(self, article: dict):
        """Send immediate alert for Score 5 articles."""
        from .line_flex_builder import build_single_article_flex

        flex = build_single_article_flex(article)
        if not flex:
            return False

        # Prepend alert text
        alert_msg = {
            "type": "text",
            "text": f"🔔 Must-read alert: Score {article.get('total_score', 5)}\n{article['title'][:60]}...",
        }

        # Send alert text first, then the flex card
        self.push_to_group(alert_msg)
        return self.push_to_group(flex)

    def send_on_demand_result(self, user_id: str, article: dict):
        """Send on-demand deep analysis result to the requesting user."""
        from .line_flex_builder import build_single_article_flex

        flex = build_single_article_flex(article)
        if not flex:
            return False

        # Notify user
        notify_msg = {
            "type": "text",
            "text": f"Deep analysis 完成 ✅\n{article['title'][:50]}...",
        }
        self.push_to_user(user_id, notify_msg)
        return self.push_to_user(user_id, flex)
