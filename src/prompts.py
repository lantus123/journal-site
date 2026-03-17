"""
Prompt templates for AI scoring and analysis.
Edit these to adjust output quality and format.
"""

# ============================================
# HAIKU: Scoring + Chinese Summary
# Used for ALL articles
# ============================================
HAIKU_SCORING_PROMPT = """你是一位台灣馬偕紀念醫院的新生兒/兒童重症專科資深主治醫師。
請根據以下 abstract，產出 JSON 格式的結構化分析。

語言規則：
- 臨床常用英文縮寫保留原文（BPD, NEC, RDS, VLBW, ELBW, NNT, RCT, ECMO, NIRS, HFOV 等）
- 藥物名稱使用英文通用名（caffeine, surfactant, dexmedetomidine 等）
- 統計數據保留原始格式（p<0.001, RR 0.72, 95% CI, OR 3.4 等）
- 文章標題保留英文原文
- 其餘所有內容一律使用繁體中文，語氣專業但簡潔

評分維度（各 1-5 分）：
A. 研究設計嚴謹度 (design): RCT=5, prospective cohort=4, retrospective=3, case series=2, case report/review=1
B. 臨床相關性 (relevance): 對 NICU/PICU 日常照護的直接影響程度 (1=無關, 5=直接影響照護)
C. 創新性 (novelty): 是否挑戰現行做法、確認爭議觀點、或引入新方法 (1=已知, 5=paradigm shift)
D. 樣本量與可推廣性 (generalizability): 多中心? 足夠power? 族群可類推到台灣? (1=case report, 5=large multicenter)

加權總分 = A×{w_design} + B×{w_relevance} + C×{w_novelty} + D×{w_generalizability}，四捨五入到整數 (1-5)

回覆純 JSON，不要任何前綴或 markdown：
{{
  "scores": {{
    "design": <int 1-5>,
    "relevance": <int 1-5>,
    "novelty": <int 1-5>,
    "generalizability": <int 1-5>
  }},
  "total": <int 1-5>,
  "summary": {{
    "purpose": "<研究目的，1-2句>",
    "design": "<研究設計與方法，含樣本數>",
    "findings": "<主要發現，含關鍵數據>",
    "significance": "<臨床意義，具體說明對 NICU/PICU 的影響>"
  }},
  "one_liner": "<一句話，為什麼這篇重要或不重要>",
  "keywords": ["<3-5個主題關鍵字，用於分類>"]
}}

---
Article metadata:
Title: {title}
Journal: {journal}
Authors: {authors}
DOI: {doi}
PMID: {pmid}
Publication Date: {pub_date}

Abstract:
{abstract}
"""

# ============================================
# SONNET: Deep Analysis (Score 4-5)
# Used only for high-scoring articles
# ============================================
SONNET_DEEP_ANALYSIS_PROMPT = """你是一位台灣馬偕紀念醫院的新生兒/兒童重症專科資深主治醫師，正在為科內同仁做文獻深度分析。

你的目標是產出「醫師自己讀 abstract 得不到」的洞見，包含：
1. Abstract 隱藏或淡化的 findings
2. 方法學的 strengths 和 weaknesses
3. 在 evidence landscape 中的定位
4. 對我們科具體 protocol 的影響

語言規則：
- 臨床常用英文縮寫保留原文
- 藥物名稱使用英文通用名
- 統計數據保留原始格式
- 其餘一律繁體中文

{protocol_context}

回覆純 JSON，不要任何前綴或 markdown：
{{
  "thirty_second_summary": "<30秒重點，3-4句，含最關鍵的數據>",
  "hidden_findings": [
    {{
      "finding": "<Abstract 沒告訴你的發現>",
      "source": "<在全文/supplementary 的什麼位置找到>",
      "implication": "<為什麼這很重要>"
    }}
  ],
  "methodology_audit": {{
    "strengths": ["<方法學優點，每項1-2句>"],
    "notes": ["<值得注意但不算缺陷的點>"],
    "weaknesses": ["<方法學缺陷，每項1-2句>"]
  }},
  "evidence_positioning": {{
    "related_studies": [
      {{
        "citation": "<Author Year, Journal>",
        "comparison": "<與本研究的關鍵差異和互補>"
      }}
    ],
    "guideline_status": "<目前主要指引（AAP/ESPGHAN/ILCOR）對此主題的立場>",
    "evidence_gap_filled": "<本研究填補了什麼 evidence gap>"
  }},
  "protocol_impact": {{
    "current_practice": "<根據工作手冊/通用做法，我們科目前怎麼做>",
    "proposed_change": "<如果採用本研究結果，具體要改什麼（劑量/頻率/監測方式）>",
    "prerequisites": ["<導入前需要什麼準備>"],
    "missing_evidence": "<還缺什麼證據才能安心改變>"
  }}
}}

---
Article metadata:
Title: {title}
Journal: {journal}
Authors: {authors}
DOI: {doi}
PMID: {pmid}
Publication Date: {pub_date}

Haiku scoring result:
{haiku_result}

{content_section}
"""

# ============================================
# Protocol context injection
# ============================================
PROTOCOL_CONTEXT_WITH_MANUAL = """【該科目前的相關 protocol（摘自工作手冊）】
以下是與本篇文章主題最相關的工作手冊段落：

{matched_chunks}

請在「protocol_impact」段落中：
1. 明確引用手冊中的具體條文或數值
2. 指出本研究結果與目前 protocol 的差異
3. 如果要採用，具體要改什麼
4. 如果手冊沒有涵蓋此主題，明確說明「目前工作手冊中無相關 protocol」
"""

PROTOCOL_CONTEXT_WITHOUT_MANUAL = """【注意】目前尚未載入科內工作手冊。
請根據一般新生兒/兒童重症照護常規做法，給出通用的臨床影響評估。
在「current_practice」中使用一般性描述（例如「多數 NICU 常見做法為...」）而非特定科室的做法。
"""

# ============================================
# Content section templates
# ============================================
CONTENT_FULLTEXT = """Full text:
{fulltext}
"""

CONTENT_ABSTRACT_ONLY = """Abstract (full text not available):
{abstract}

注意：由於無法取得全文，「hidden_findings」段落請改為分析 abstract 中值得深入探討的方法學細節或暗示性發現。
"""
