"""
Full text retrieval via Unpaywall API.
Attempts to find Open Access full text for articles.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"


class FulltextFetcher:
    """Attempt to retrieve OA full text for articles."""

    def __init__(self):
        self.email = os.environ.get("UNPAYWALL_EMAIL", "nicu-bot@example.com")

    def try_fetch(self, article: dict) -> dict:
        """
        Try to get full text for an article.
        Adds 'fulltext' and 'fulltext_source' keys to the article dict.
        """
        doi = article.get("doi", "")
        if not doi:
            return article

        try:
            url = UNPAYWALL_URL.format(doi=doi)
            resp = requests.get(
                url,
                params={"email": self.email},
                timeout=15,
            )
            if resp.status_code != 200:
                return article

            data = resp.json()
            if not data.get("is_oa"):
                return article

            # Find best OA location
            best_url = data.get("best_oa_location", {}).get("url_for_pdf", "")
            if not best_url:
                best_url = data.get("best_oa_location", {}).get("url", "")

            if best_url:
                article["oa_url"] = best_url
                article["is_oa"] = True
                logger.info(f"  OA found for {doi}: {best_url}")
                # Note: actual full text extraction from PDF would go here
                # For Phase 1, we just flag it as OA and include the URL
                # Phase 3 will add PDF extraction

        except Exception as e:
            logger.debug(f"  Unpaywall lookup failed for {doi}: {e}")

        return article

    def enrich_articles(self, articles: list[dict]) -> list[dict]:
        """Try to find OA full text for all articles."""
        for i, article in enumerate(articles):
            articles[i] = self.try_fetch(article)
        oa_count = sum(1 for a in articles if a.get("is_oa"))
        logger.info(f"OA availability: {oa_count}/{len(articles)} articles")
        return articles
