"""
PubMed E-utilities API client.
Fetches new articles from configured journals.
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EFETCH_URL = f"{BASE_URL}/efetch.fcgi"
ESEARCH_URL = f"{BASE_URL}/esearch.fcgi"


class PubMedFetcher:
    """Fetch new articles from PubMed."""

    def __init__(self, config: dict, cache_path: str = "data/pmid_cache.json"):
        self.config = config
        self.cache_path = Path(cache_path)
        self.api_key = os.environ.get(config.get("pubmed", {}).get("api_key_env", ""), "")
        self.lookback_hours = config.get("pubmed", {}).get("lookback_hours", 48)
        self.max_results = config.get("pubmed", {}).get("max_results_per_journal", 20)
        self.cache = self._load_cache()
        self._request_count = 0

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            with open(self.cache_path) as f:
                return json.load(f)
        return {}

    def save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self.cache, f, indent=2)

    def _rate_limit(self):
        """Respect NCBI rate limits: 3/s without key, 10/s with key."""
        self._request_count += 1
        delay = 0.1 if self.api_key else 0.34
        time.sleep(delay)

    def _make_params(self, **kwargs) -> dict:
        params = dict(kwargs)
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def search_journal(self, journal_config: dict) -> list[str]:
        """Search PubMed for recent articles in a journal. Returns list of PMIDs."""
        now = datetime.now(timezone.utc)
        lookback = now - timedelta(hours=self.lookback_hours)
        date_range = f"{lookback.strftime('%Y/%m/%d')}:{now.strftime('%Y/%m/%d')}[edat]"

        query = f"{journal_config['query']} AND {date_range}"
        logger.info(f"Searching: {journal_config['name']} -> {query}")

        self._rate_limit()
        try:
            resp = requests.get(
                ESEARCH_URL,
                params=self._make_params(
                    db="pubmed",
                    term=query,
                    retmax=self.max_results,
                    retmode="json",
                    sort="date",
                ),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            pmids = data.get("esearchresult", {}).get("idlist", [])
            logger.info(f"  Found {len(pmids)} articles")
            return pmids
        except Exception as e:
            logger.error(f"  Search failed: {e}")
            return []

    def fetch_details(self, pmids: list[str]) -> list[dict]:
        """Fetch detailed article metadata for a list of PMIDs."""
        if not pmids:
            return []

        self._rate_limit()
        try:
            resp = requests.get(
                EFETCH_URL,
                params=self._make_params(
                    db="pubmed",
                    id=",".join(pmids),
                    rettype="xml",
                    retmode="xml",
                ),
                timeout=60,
            )
            resp.raise_for_status()
            return self._parse_articles(resp.text)
        except Exception as e:
            logger.error(f"Fetch details failed: {e}")
            return []

    def _parse_articles(self, xml_text: str) -> list[dict]:
        """Parse PubMed XML response into structured dicts."""
        articles = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return []

        for article_elem in root.findall(".//PubmedArticle"):
            try:
                articles.append(self._parse_single_article(article_elem))
            except Exception as e:
                logger.warning(f"Failed to parse article: {e}")
                continue

        return articles

    def _parse_single_article(self, elem) -> dict:
        """Parse a single PubmedArticle element."""
        medline = elem.find(".//MedlineCitation")
        article = medline.find(".//Article")

        # PMID
        pmid = medline.findtext("PMID", "")

        # Title
        title = article.findtext(".//ArticleTitle", "")

        # Abstract
        abstract_parts = []
        for abs_text in article.findall(".//Abstract/AbstractText"):
            label = abs_text.get("Label", "")
            text = "".join(abs_text.itertext())
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = "\n".join(abstract_parts)

        # Authors
        authors = []
        for author in article.findall(".//AuthorList/Author"):
            last = author.findtext("LastName", "")
            initials = author.findtext("Initials", "")
            if last:
                authors.append(f"{last} {initials}".strip())
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += ", et al."

        # Journal
        journal = article.findtext(".//Journal/Title", "")
        journal_abbr = article.findtext(".//Journal/ISOAbbreviation", "")

        # DOI
        doi = ""
        for id_elem in article.findall(".//ELocationID"):
            if id_elem.get("EIdType") == "doi":
                doi = id_elem.text or ""
                break

        # Publication date
        pub_date = ""
        pd = article.find(".//Journal/JournalIssue/PubDate")
        if pd is not None:
            year = pd.findtext("Year", "")
            month = pd.findtext("Month", "")
            day = pd.findtext("Day", "")
            pub_date = f"{year} {month} {day}".strip()
            if not pub_date:
                pub_date = pd.findtext("MedlineDate", "")

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": author_str,
            "journal": journal,
            "journal_abbr": journal_abbr,
            "doi": doi,
            "pub_date": pub_date,
        }

    def _matches_filter(self, article: dict, filter_keywords: list[str]) -> bool:
        """Check if article matches keyword filter (for general journals)."""
        if not filter_keywords:
            return True
        text = f"{article['title']} {article['abstract']}".lower()
        return any(kw.lower() in text for kw in filter_keywords)

    def fetch_new_articles(self) -> list[dict]:
        """
        Main method: fetch all new articles across all configured journals.
        Deduplicates against cache. Returns list of article dicts.
        """
        all_articles = []

        for journal_cfg in self.config.get("journals", []):
            pmids = self.search_journal(journal_cfg)

            # Filter out already-processed PMIDs
            new_pmids = [p for p in pmids if p not in self.cache]
            if not new_pmids:
                logger.info(f"  No new articles for {journal_cfg['name']}")
                continue

            # Fetch details
            articles = self.fetch_details(new_pmids)

            # Apply keyword filter for general journals
            filter_kw = journal_cfg.get("filter_keywords", [])
            if filter_kw:
                before = len(articles)
                articles = [a for a in articles if self._matches_filter(a, filter_kw)]
                logger.info(f"  Keyword filter: {before} -> {len(articles)} articles")

            # Tag with source journal config
            for a in articles:
                a["source_journal"] = journal_cfg["name"]
                a["category"] = journal_cfg.get("category", "other")

            all_articles.extend(articles)

        # Update cache with all fetched PMIDs
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for article in all_articles:
            self.cache[article["pmid"]] = today

        logger.info(f"Total new articles: {len(all_articles)}")
        return all_articles
