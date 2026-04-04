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
        self._synonym_map = self._build_synonym_map()

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

    # Synonym groups for improved keyword matching.
    # Each group contains terms that should be treated as equivalent.
    SYNONYM_GROUPS = [
        {"surfactant", "survanta", "curosurf", "poractant", "beractant", "lisa", "界面活性劑"},
        {"rds", "respiratory distress syndrome", "呼吸窘迫症", "呼吸窘迫症候群"},
        {"bpd", "bronchopulmonary dysplasia", "chronic lung disease", "cld", "支氣管肺發育不全"},
        {"nec", "necrotizing enterocolitis", "壞死性腸炎"},
        {"pda", "patent ductus arteriosus", "開放性動脈導管", "ibuprofen", "indomethacin", "acetaminophen"},
        {"rop", "retinopathy of prematurity", "早產兒視網膜病變", "bevacizumab", "ranibizumab"},
        {"ivh", "intraventricular hemorrhage", "腦室內出血", "germinal matrix"},
        {"pvl", "periventricular leukomalacia", "腦室周圍白質軟化"},
        {"hie", "hypoxic ischemic encephalopathy", "缺氧缺血性腦病變", "therapeutic hypothermia", "低溫治療", "cooling"},
        {"pphn", "persistent pulmonary hypertension", "持續性肺高壓", "ino", "inhaled nitric oxide", "sildenafil"},
        {"hfov", "high frequency oscillatory ventilation", "高頻震盪"},
        {"cpap", "continuous positive airway pressure", "nippv", "nimv", "連續性氣道正壓"},
        {"caffeine", "aminophylline", "theophylline", "apnea", "aop", "呼吸暫停"},
        {"phototherapy", "光照治療", "jaundice", "黃疸", "hyperbilirubinemia", "高膽紅素血症", "exchange transfusion", "換血"},
        {"sepsis", "敗血症", "meningitis", "腦膜炎", "antibiotic", "抗生素"},
        {"tpn", "parenteral nutrition", "全靜脈營養", "lipid", "amino acid"},
        {"anemia", "貧血", "transfusion", "輸血", "erythropoietin", "epo"},
        {"hypothyroidism", "甲狀腺低下", "thyroid", "甲狀腺", "levothyroxine"},
        {"glucose", "hypoglycemia", "低血糖", "hyperglycemia", "高血糖", "insulin"},
        {"ecmo", "extracorporeal membrane oxygenation", "葉克膜"},
        {"aki", "acute kidney injury", "急性腎損傷", "renal", "腎臟"},
        {"feeding", "餵食", "breast milk", "母乳", "formula", "配方奶", "fortifier"},
        {"ventilator", "呼吸器", "mechanical ventilation", "extubation", "拔管", "intubation", "插管"},
        {"steroid", "dexamethasone", "hydrocortisone", "類固醇"},
        {"seizure", "抽搐", "癲癇", "phenobarbital", "levetiracetam"},
        {"chylothorax", "乳糜胸"},
        {"pneumothorax", "氣胸", "air leak"},
        {"mas", "meconium aspiration", "胎便吸入"},
        {"ttnb", "transient tachypnea", "暫時性呼吸急促"},
        {"hemorrhage", "出血", "pulmonary hemorrhage", "肺出血"},
        {"nava", "neurally adjusted ventilatory assist"},
        {"thrombocytopenia", "血小板低下", "platelet"},
        {"polycythemia", "紅血球過多症"},
        {"dic", "disseminated intravascular coagulation", "瀰散性血管內凝血"},
    ]

    def _build_synonym_map(self) -> dict[str, set[str]]:
        """Build synonym lookup: term -> set of all synonyms."""
        syn_map = {}
        for group in self.SYNONYM_GROUPS:
            lower_group = {t.lower() for t in group}
            for term in lower_group:
                syn_map[term] = lower_group
        return syn_map

    def _expand_synonyms(self, terms: set[str]) -> set[str]:
        """Expand a set of terms with their synonyms."""
        expanded = set(terms)
        for term in terms:
            if term in self._synonym_map:
                expanded |= self._synonym_map[term]
        return expanded

    def _get_protocol_context(self, article: dict) -> str:
        """Find relevant manual chunks for this article's topic."""
        if not self.manual_chunks:
            return PROTOCOL_CONTEXT_WITHOUT_MANUAL

        keywords = article.get("keywords", [])
        title_words = article.get("title", "").lower().split()
        search_terms = set(kw.lower() for kw in keywords) | set(title_words)
        # Expand with synonyms for broader matching
        search_terms = self._expand_synonyms(search_terms)

        scored_chunks = []
        for chunk in self.manual_chunks:
            chunk_text = chunk.get("content", "").lower()
            chunk_keywords = set(kw.lower() for kw in chunk.get("keywords", []))
            # Expand chunk keywords with synonyms too
            chunk_keywords_expanded = self._expand_synonyms(chunk_keywords)
            # Score by keyword overlap (expanded)
            overlap = len(search_terms & chunk_keywords_expanded)
            # Also check content match
            content_matches = sum(1 for term in search_terms if term in chunk_text)
            score = overlap * 3 + content_matches
            if score > 0:
                scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored_chunks[:3]

        if not top_chunks:
            return PROTOCOL_CONTEXT_WITHOUT_MANUAL

        # Truncate oversized chunks to avoid token bloat
        chunks_text = "\n\n---\n\n".join(
            f"【{c['path']}】\n{c['content'][:3000]}" for _, c in top_chunks
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
