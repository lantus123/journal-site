"""
Full text retrieval via PMC and Unpaywall.
- PMC: free structured full text for articles in PubMed Central
- Unpaywall: OA URL detection for articles not in PMC
"""

import os
import logging
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
PMC_IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
PMC_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

MAX_FULLTEXT_CHARS = 8000


class FulltextFetcher:
    """Attempt to retrieve full text for articles via PMC, then Unpaywall."""

    def __init__(self):
        self.email = os.environ.get("UNPAYWALL_EMAIL", "nicu-bot@example.com")
        self.ncbi_api_key = os.environ.get("NCBI_API_KEY", "")

    def _pmid_to_pmcid(self, pmid: str) -> str | None:
        """Convert PMID to PMCID using NCBI ID Converter API."""
        try:
            resp = requests.get(
                PMC_IDCONV_URL,
                params={
                    "ids": pmid,
                    "format": "json",
                    "tool": "nicu-journal-bot",
                    "email": self.email,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            records = data.get("records", [])
            if records and records[0].get("pmcid"):
                return records[0]["pmcid"]
        except Exception as e:
            logger.debug(f"  ID conversion failed for PMID {pmid}: {e}")
        return None

    def _fetch_pmc_fulltext(self, pmcid: str) -> str | None:
        """Fetch and parse full text from PMC XML."""
        try:
            params = {
                "db": "pmc",
                "id": pmcid,
                "rettype": "xml",
                "tool": "nicu-journal-bot",
                "email": self.email,
            }
            if self.ncbi_api_key:
                params["api_key"] = self.ncbi_api_key

            resp = requests.get(PMC_EFETCH_URL, params=params, timeout=30)
            if resp.status_code != 200:
                return None

            return self._parse_pmc_xml(resp.text)

        except Exception as e:
            logger.debug(f"  PMC fetch failed for {pmcid}: {e}")
        return None

    def _parse_pmc_xml(self, xml_text: str) -> str | None:
        """Extract structured text from PMC XML."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        body = root.find(".//body")
        if body is None:
            return None

        sections = []
        for sec in body.findall(".//sec"):
            title_el = sec.find("title")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            paragraphs = []
            for p in sec.findall("p"):
                text = "".join(p.itertext()).strip()
                if text:
                    paragraphs.append(text)

            if paragraphs:
                if title:
                    sections.append(f"## {title}\n" + "\n".join(paragraphs))
                else:
                    sections.append("\n".join(paragraphs))

        if not sections:
            # Fallback: extract all text from body
            all_text = "".join(body.itertext()).strip()
            if all_text:
                sections.append(all_text)

        if not sections:
            return None

        fulltext = "\n\n".join(sections)

        # Truncate to limit
        if len(fulltext) > MAX_FULLTEXT_CHARS:
            fulltext = fulltext[:MAX_FULLTEXT_CHARS] + "\n\n[... truncated]"

        return fulltext

    def _try_pmc(self, article: dict) -> bool:
        """Try to get full text from PMC. Returns True if successful."""
        pmid = article.get("pmid", "")
        if not pmid:
            return False

        pmcid = self._pmid_to_pmcid(pmid)
        if not pmcid:
            return False

        fulltext = self._fetch_pmc_fulltext(pmcid)
        if not fulltext:
            return False

        article["fulltext"] = fulltext
        article["fulltext_source"] = "pmc"
        article["pmcid"] = pmcid
        logger.info(f"  PMC fulltext for PMID {pmid} ({pmcid}): {len(fulltext)} chars")
        return True

    def _try_unpaywall(self, article: dict) -> bool:
        """Try to detect OA via Unpaywall. Returns True if OA found."""
        doi = article.get("doi", "")
        if not doi:
            return False

        try:
            url = UNPAYWALL_URL.format(doi=doi)
            resp = requests.get(
                url,
                params={"email": self.email},
                timeout=15,
            )
            if resp.status_code != 200:
                return False

            data = resp.json()
            if not data.get("is_oa"):
                return False

            best_url = data.get("best_oa_location", {}).get("url_for_pdf", "")
            if not best_url:
                best_url = data.get("best_oa_location", {}).get("url", "")

            if best_url:
                article["oa_url"] = best_url
                article["is_oa"] = True
                logger.info(f"  OA found for {doi}: {best_url}")
                return True

        except Exception as e:
            logger.debug(f"  Unpaywall lookup failed for {doi}: {e}")
        return False

    def try_fetch(self, article: dict) -> dict:
        """
        Try to get full text for an article.
        1. PMC (free structured full text)
        2. Unpaywall (OA URL detection)
        """
        # Try PMC first
        if self._try_pmc(article):
            # Also check Unpaywall for OA URL (useful for web digest link)
            self._try_unpaywall(article)
            return article

        # Fall back to Unpaywall
        self._try_unpaywall(article)
        return article

    def enrich_articles(self, articles: list[dict]) -> list[dict]:
        """Try to find full text for all articles."""
        for i, article in enumerate(articles):
            articles[i] = self.try_fetch(article)

        pmc_count = sum(1 for a in articles if a.get("fulltext_source") == "pmc")
        oa_count = sum(1 for a in articles if a.get("is_oa"))
        logger.info(
            f"Fulltext: {pmc_count}/{len(articles)} from PMC, "
            f"{oa_count}/{len(articles)} OA detected"
        )
        return articles
