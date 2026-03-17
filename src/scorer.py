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

    def __init__(self, llm: LLMClient, scoring_config: dict):
        self.llm = llm
        self.config = scoring_config
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

    def _load_manual_chunks(self) -> list[dict]:
        """Load pre-processed manual chunks if available."""
        chunks_path = Path("data/manual_chunks.json")
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
        boost = sum(topic_boost.get(kw, 0) for kw in keywords)
        original_total = result.get("total", 3)
        boosted_total = min(5, max(1, round(original_total + boost)))

        # Merge results into article
        article["scores"] = result.get("scores", {})
        article["total_score"] = boosted_total
        article["original_score"] = original_total
        article["summary"] = result.get("summary", {})
        article["one_liner"] = result.get("one_liner", "")
        article["keywords"] = keywords

        logger.info(
            f"  [{article['pmid']}] Score: {boosted_total} "
            f"({'↑' + str(round(boost, 1)) if boost > 0 else 'no boost'}) "
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
