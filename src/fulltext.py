"""
Full text retrieval via manual PDF, PMC, Elsevier, and Unpaywall.
- Manual PDF: uploaded by users via web digest
- PMC: free structured full text for articles in PubMed Central
- Elsevier: full text for subscribed Elsevier journals via API
- Unpaywall: OA URL detection for articles not in PMC/Elsevier
"""

import json
import os
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
PMC_IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
PMC_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ELSEVIER_FULLTEXT_URL = "https://api.elsevier.com/content/article/doi/{doi}"

MAX_FULLTEXT_CHARS = 8000


ELSEVIER_JOURNALS = {
    "Early Human Development",
    "Seminars in Fetal and Neonatal Medicine",
    "Seminars in Perinatology",
    "The Lancet",
}


class FulltextFetcher:
    """Attempt to retrieve full text via PMC, Elsevier, then Unpaywall."""

    def __init__(self, dept: str = "newborn"):
        self.dept = dept
        self.email = os.environ.get("UNPAYWALL_EMAIL", "nicu-bot@example.com")
        self.ncbi_api_key = os.environ.get("NCBI_API_KEY", "")
        self.elsevier_api_key = os.environ.get("ELSEVIER_API_KEY", "")

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

    def _try_existing_analysis(self, article: dict) -> bool:
        """Check if a pre-computed PDF analysis exists."""
        pmid = article.get("pmid", "")
        if not pmid:
            return False
        analysis_path = Path(f"data/{self.dept}/pdf_analyses/{pmid}.json")
        if not analysis_path.exists():
            return False
        try:
            with open(analysis_path) as f:
                data = json.load(f)
            article["deep_analysis"] = data.get("deep_analysis", {})
            article["fulltext_source"] = "manual"
            logger.info(f"  Pre-computed analysis for PMID {pmid}")
            return True
        except Exception as e:
            logger.debug(f"  Failed to load analysis for PMID {pmid}: {e}")
        return False

    def _try_manual_pdf(self, article: dict) -> bool:
        """Check for manually uploaded PDF in data/pdfs/."""
        pmid = article.get("pmid", "")
        if not pmid:
            return False
        pdf_path = Path(f"data/pdfs/{pmid}.pdf")
        if not pdf_path.exists():
            return False
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(pdf_path))
            text_parts = []
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()
            fulltext = "\n".join(text_parts).strip()
            if not fulltext or len(fulltext) < 100:
                return False
            if len(fulltext) > MAX_FULLTEXT_CHARS:
                fulltext = fulltext[:MAX_FULLTEXT_CHARS] + "\n\n[... truncated]"
            article["fulltext"] = fulltext
            article["fulltext_source"] = "manual"
            logger.info(f"  Manual PDF for PMID {pmid}: {len(fulltext)} chars")
            return True
        except ImportError:
            logger.warning("  PyMuPDF not installed, skipping manual PDF")
        except Exception as e:
            logger.debug(f"  Failed to read PDF for PMID {pmid}: {e}")
        return False

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

    def _try_elsevier(self, article: dict) -> bool:
        """Try to get full text from Elsevier API. Returns True if successful."""
        if not self.elsevier_api_key:
            return False

        doi = article.get("doi", "")
        journal = article.get("source_journal", article.get("journal", ""))
        if not doi or journal not in ELSEVIER_JOURNALS:
            return False

        try:
            url = ELSEVIER_FULLTEXT_URL.format(doi=doi)
            resp = requests.get(
                url,
                headers={
                    "X-ELS-APIKey": self.elsevier_api_key,
                    "Accept": "text/xml",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                logger.debug(f"  Elsevier API {resp.status_code} for {doi}")
                return False

            fulltext = self._parse_elsevier_xml(resp.text)
            if not fulltext:
                return False

            article["fulltext"] = fulltext
            article["fulltext_source"] = "elsevier"
            logger.info(f"  Elsevier fulltext for {doi}: {len(fulltext)} chars")
            return True

        except Exception as e:
            logger.debug(f"  Elsevier fetch failed for {doi}: {e}")
        return False

    def _parse_elsevier_xml(self, xml_text: str) -> str | None:
        """Extract text from Elsevier full-text XML."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        # Elsevier uses namespaces; find all sections and paragraphs
        ns = {
            "ce": "http://www.elsevier.com/xml/common/dtd",
            "ja": "http://www.elsevier.com/xml/ja/dtd",
            "xocs": "http://www.elsevier.com/xml/xocs/dtd",
        }

        sections = []

        # Try structured sections first
        for sec in root.findall(".//ce:sections/ce:section", ns):
            title_el = sec.find("ce:section-title", ns)
            title = "".join(title_el.itertext()).strip() if title_el is not None else ""

            paragraphs = []
            for para in sec.findall(".//ce:para", ns):
                text = "".join(para.itertext()).strip()
                if text:
                    paragraphs.append(text)

            if paragraphs:
                if title:
                    sections.append(f"## {title}\n" + "\n".join(paragraphs))
                else:
                    sections.append("\n".join(paragraphs))

        # Fallback: grab all ce:para elements
        if not sections:
            for para in root.findall(".//ce:para", ns):
                text = "".join(para.itertext()).strip()
                if text:
                    sections.append(text)

        if not sections:
            return None

        fulltext = "\n\n".join(sections)

        if len(fulltext) > MAX_FULLTEXT_CHARS:
            fulltext = fulltext[:MAX_FULLTEXT_CHARS] + "\n\n[... truncated]"

        return fulltext

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
        1. Existing analysis (pre-computed via web upload)
        2. Manual PDF (uploaded but not yet analyzed)
        3. PMC (free structured full text)
        4. Elsevier API (subscribed journals)
        5. Unpaywall (OA URL detection)
        """
        # Check for pre-computed analysis from web upload
        if self._try_existing_analysis(article):
            self._try_unpaywall(article)
            return article

        # Check for manually uploaded PDF
        if self._try_manual_pdf(article):
            self._try_unpaywall(article)
            return article

        # Try PMC
        if self._try_pmc(article):
            self._try_unpaywall(article)
            return article

        # Try Elsevier for subscribed journals
        if self._try_elsevier(article):
            self._try_unpaywall(article)
            return article

        # Fall back to Unpaywall
        self._try_unpaywall(article)
        return article

    def enrich_articles(self, articles: list[dict]) -> list[dict]:
        """Try to find full text for all articles."""
        for i, article in enumerate(articles):
            articles[i] = self.try_fetch(article)

        manual_count = sum(1 for a in articles if a.get("fulltext_source") == "manual")
        pmc_count = sum(1 for a in articles if a.get("fulltext_source") == "pmc")
        els_count = sum(1 for a in articles if a.get("fulltext_source") == "elsevier")
        oa_count = sum(1 for a in articles if a.get("is_oa"))
        ft_total = manual_count + pmc_count + els_count
        logger.info(
            f"Fulltext: {ft_total}/{len(articles)} "
            f"(manual: {manual_count}, PMC: {pmc_count}, Elsevier: {els_count}), "
            f"OA detected: {oa_count}/{len(articles)}"
        )
        return articles
