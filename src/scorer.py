"""
Article scorer and deep analyzer.
- Haiku: scores all articles + produces Chinese summary
- Sonnet: deep analysis for score 4-5 articles
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .llm import LLMClient
from .prompts import (
    HAIKU_SCORING_PROMPT,
    SONNET_DEEP_ANALYSIS_PROMPT,
    PROTOCOL_CONTEXT_WITH_MANUAL,
    PROTOCOL_CONTEXT_WITHOUT_MANUAL,
    CONTENT_FULLTEXT,
    CONTENT_ABSTRACT_ONLY,
)

logger = logging.getLogger(__name__)


class ArticleScorer:
    """Score and analyze articles using Claude Haiku/Sonnet."""

    def __init__(self, llm: LLMClient, scoring_config: dict, dept: str = "newborn"):
        self.llm = llm
        self.config = scoring_config
        self.dept = dept
        self.weights = self._load_weights()
        self.deep_threshold = (
            scoring_config.get("model_routing", {}).get("deep_analysis_threshold", 4)
        )
        self.manual_chunks = self._load_manual_chunks()

    def _load_weights(self) -> dict:
        """Extract scoring weights from config."""
        weights = {}
        for dim in self.config.get("scoring", {}).get("dimensions", []):
            weights[dim["id"]] = dim["weight"]
        return weights

    def _get_if_boost(self, article: dict) -> float:
        """Get Impact Factor tier boost for the article's journal."""
        if_config = self.config.get("if_tier_boost", {})
        journal = article.get("source_journal", article.get("journal", ""))
        for tier_key in ("top_tier", "high_tier"):
            tier = if_config.get(tier_key, {})
            journals = tier.get("journals", [])
            if journal in journals:
                return tier.get("boost", 0)
        return 0.0

    def _load_manual_chunks(self) -> list[dict]:
        """Load pre-processed manual chunks if available."""
        chunks_path = Path(f"data/{self.dept}/manual_chunks.json")
        if chunks_path.exists():
            with open(chunks_path) as f:
                chunks = json.load(f)
            logger.info(f"Loaded {len(chunks)} manual chunks")
            return chunks
        logger.info("No manual chunks found - using generic protocol context")
        return []

    def score_article(self, article: dict) -> Optional[dict]:
        """
        Score a single article with Haiku.
        Returns enriched article dict with scores and summary.
        """
        prompt = HAIKU_SCORING_PROMPT.format(
            w_design=self.weights.get("design", 0.25),
            w_relevance=self.weights.get("relevance", 0.30),
            w_novelty=self.weights.get("novelty", 0.25),
            w_generalizability=self.weights.get("generalizability", 0.20),
            title=article["title"],
            journal=article.get("source_journal", article.get("journal", "")),
            authors=article["authors"],
            doi=article.get("doi", "N/A"),
            pmid=article["pmid"],
            pub_date=article.get("pub_date", "N/A"),
            abstract=article.get("abstract", "No abstract available"),
        )

        result = self.llm.call_json(prompt, model_key="haiku")
        if not result:
            logger.error(f"Scoring failed for PMID {article['pmid']}")
            return None

        # Apply topic boost
        topic_boost = self.config.get("topic_boost", {})
        keywords = result.get("keywords", [])
        topic_boost_val = sum(topic_boost.get(kw, 0) for kw in keywords)

        # Apply IF tier boost
        if_boost_val = self._get_if_boost(article)

        original_total = result.get("total", 3)
        total_boost = topic_boost_val + if_boost_val
        # Cap: boost cannot increase score by more than 1
        total_boost = min(total_boost, 1.0)
        boosted_total = min(5, max(1, round(original_total + total_boost)))

        # Merge results into article
        article["scores"] = result.get("scores", {})
        article["total_score"] = boosted_total
        article["original_score"] = original_total
        article["summary"] = result.get("summary", {})
        article["one_liner"] = result.get("one_liner", "")
        article["keywords"] = keywords
        article["if_boost"] = if_boost_val

        boost_info = []
        if topic_boost_val > 0:
            boost_info.append(f"topic+{round(topic_boost_val, 1)}")
        if if_boost_val > 0:
            boost_info.append(f"IF+{round(if_boost_val, 1)}")
        boost_str = "↑" + ",".join(boost_info) if boost_info else "no boost"

        logger.info(
            f"  [{article['pmid']}] Score: {boosted_total} "
            f"({boost_str}) "
            f"- {article['title'][:60]}..."
        )
        return article

    def deep_analyze(self, article: dict) -> Optional[dict]:
        """
        Deep analysis with Sonnet for high-scoring articles.
        Injects relevant protocol context from manual if available.
        """
        if article.get("total_score", 0) < self.deep_threshold:
            return article

        # Skip if pre-computed analysis exists (from web PDF upload)
        if article.get("deep_analysis") and article.get("fulltext_source") == "manual":
            logger.info(f"  Using pre-computed analysis for PMID {article['pmid']}")
            return article

        logger.info(f"  Deep analysis for PMID {article['pmid']}...")

        # Build protocol context
        protocol_context = self._get_protocol_context(article)

        # Build content section (fulltext vs abstract)
        fulltext = article.get("fulltext")
        if fulltext:
            content_section = CONTENT_FULLTEXT.format(fulltext=fulltext)
        else:
            content_section = CONTENT_ABSTRACT_ONLY.format(
                abstract=article.get("abstract", "No abstract available")
            )

        # Build Haiku result summary for context
        haiku_result = json.dumps(
            {
                "scores": article.get("scores", {}),
                "total": article.get("total_score", 0),
                "summary": article.get("summary", {}),
                "keywords": article.get("keywords", []),
            },
            ensure_ascii=False,
            indent=2,
        )

        prompt = SONNET_DEEP_ANALYSIS_PROMPT.format(
            protocol_context=protocol_context,
            title=article["title"],
            journal=article.get("source_journal", article.get("journal", "")),
            authors=article["authors"],
            doi=article.get("doi", "N/A"),
            pmid=article["pmid"],
            pub_date=article.get("pub_date", "N/A"),
            haiku_result=haiku_result,
            content_section=content_section,
        )

        result = self.llm.call_json(prompt, model_key="sonnet", max_tokens=6000)
        if not result:
            logger.error(f"Deep analysis failed for PMID {article['pmid']}")
            return article

        article["deep_analysis"] = result
        logger.info(f"  Deep analysis complete for PMID {article['pmid']}")
        return article

    def _get_protocol_context(self, article: dict) -> str:
        """Find relevant manual chunks for this article's topic."""
        if not self.manual_chunks:
            return PROTOCOL_CONTEXT_WITHOUT_MANUAL

        # Simple keyword matching for now
        # Phase 3 will upgrade to embedding-based semantic search
        keywords = article.get("keywords", [])
        title_words = article.get("title", "").lower().split()
        search_terms = set(kw.lower() for kw in keywords) | set(title_words)

        scored_chunks = []
        for chunk in self.manual_chunks:
            chunk_text = chunk.get("content", "").lower()
            chunk_keywords = set(kw.lower() for kw in chunk.get("keywords", []))
            # Score by keyword overlap
            overlap = len(search_terms & chunk_keywords)
            # Also check content match
            content_matches = sum(1 for term in search_terms if term in chunk_text)
            score = overlap * 3 + content_matches
            if score > 0:
                scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored_chunks[:3]

        if not top_chunks:
            return PROTOCOL_CONTEXT_WITHOUT_MANUAL

        chunks_text = "\n\n---\n\n".join(
            f"【{c['path']}】\n{c['content']}" for _, c in top_chunks
        )
        return PROTOCOL_CONTEXT_WITH_MANUAL.format(matched_chunks=chunks_text)

    def process_all(self, articles: list[dict]) -> list[dict]:
        """Score all articles, then deep-analyze high scorers."""
        scored = []
        for article in articles:
            result = self.score_article(article)
            if result:
                scored.append(result)

        # Sort by score descending
        scored.sort(key=lambda a: a.get("total_score", 0), reverse=True)

        # Deep analyze high scorers
        for i, article in enumerate(scored):
            if article.get("total_score", 0) >= self.deep_threshold:
                scored[i] = self.deep_analyze(article) or article

        return scored
