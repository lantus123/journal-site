"""
LINE Flex Message builder.
Converts scored articles into Flex Message JSON for LINE Messaging API.
"""

import json
from typing import Optional


def build_digest_flex(articles: list[dict], on_demand: list[dict] = None) -> list[dict]:
    """
    Build Flex Message bubbles for Score 4-5 + on-demand articles only.
    Score 2-3 articles are handled as text messages in push_line.py.
    """
    on_demand = on_demand or []
    bubbles = []

    total = len(articles) + len(on_demand)
    must_read = sum(1 for a in articles if a.get("total_score", 0) == 5)

    bubbles.append(_header_bubble(total, must_read, len(on_demand)))

    # On-demand articles first
    for a in on_demand:
        b = _deep_article_bubble(a, is_on_demand=True)
        if b:
            bubbles.append(b)

    # Score 4-5 with deep analysis
    for a in articles:
        b = _deep_article_bubble(a)
        if b:
            bubbles.append(b)

    # LINE carousel max 12 bubbles
    bubbles = bubbles[:12]

    return {
        "type": "flex",
        "altText": f"NICU Journal Digest - {total} articles (Score 4-5)",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


def build_single_article_flex(article: dict) -> dict:
    """Build a single Flex Message for instant alert or on-demand response."""
    bubble = _deep_article_bubble(article) or _summary_article_bubble(article)
    if not bubble:
        return None
    return {
        "type": "flex",
        "altText": f"[Score {article.get('total_score', '?')}] {article['title'][:40]}...",
        "contents": bubble,
    }


def _header_bubble(total: int, must_read: int, on_demand: int) -> dict:
    stats = f"{total} articles"
    if must_read:
        stats += f" · {must_read} must-read"
    if on_demand:
        stats += f" · {on_demand} requested"

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "NICU/PICU Journal Digest",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1B6B93",
                },
                {
                    "type": "text",
                    "text": stats,
                    "size": "xs",
                    "color": "#888888",
                    "margin": "sm",
                },
            ],
            "paddingAll": "16px",
            "backgroundColor": "#F8FAFB",
        },
    }


def _score_color(score: int) -> tuple[str, str]:
    """Return (bg_color, text_color) for score badge."""
    if score >= 5:
        return "#EEEDFE", "#3C3489"
    elif score >= 4:
        return "#E1F5EE", "#085041"
    elif score >= 3:
        return "#F1EFE8", "#5F5E5A"
    else:
        return "#FAEEDA", "#633806"


def _deep_article_bubble(article: dict, is_on_demand: bool = False) -> Optional[dict]:
    """Build a bubble for Score 4-5 article with deep analysis."""
    score = article.get("total_score", 0)
    deep = article.get("deep_analysis", {})
    summary = article.get("summary", {})
    pmid = article.get("pmid", "")
    badge_bg, badge_color = _score_color(score)

    # Tags row
    tags = [
        {
            "type": "text",
            "text": f"Score {score}",
            "size": "xxs",
            "color": badge_color,
            "weight": "bold",
            "flex": 0,
            "decoration": "none",
        },
        {
            "type": "text",
            "text": article.get("source_journal", ""),
            "size": "xxs",
            "color": "#888888",
            "flex": 0,
        },
    ]
    if is_on_demand:
        tags.append({
            "type": "text",
            "text": "Colleague requested",
            "size": "xxs",
            "color": "#0C447C",
            "weight": "bold",
            "flex": 0,
        })

    body_contents = [
        # Tags
        {
            "type": "box",
            "layout": "horizontal",
            "contents": tags,
            "spacing": "sm",
        },
        # Title
        {
            "type": "text",
            "text": article["title"][:100] + ("..." if len(article["title"]) > 100 else ""),
            "weight": "bold",
            "size": "sm",
            "wrap": True,
            "maxLines": 3,
            "margin": "md",
        },
        # Authors
        {
            "type": "text",
            "text": article.get("authors", ""),
            "size": "xxs",
            "color": "#999999",
            "margin": "xs",
        },
    ]

    # Deep analysis content
    if deep:
        thirty_sec = deep.get("thirty_second_summary", "")
        if thirty_sec:
            body_contents.append({"type": "separator", "margin": "lg"})
            body_contents.append({
                "type": "text",
                "text": f"30 秒重點：{thirty_sec}",
                "size": "xs",
                "color": "#444444",
                "wrap": True,
                "margin": "md",
            })

        # Methodology highlights
        meth = deep.get("methodology_audit", {})
        strengths = meth.get("strengths", [])
        weaknesses = meth.get("weaknesses", [])
        if strengths:
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "Strong", "size": "xxs", "color": "#27500A",
                     "weight": "bold", "flex": 0},
                    {"type": "text", "text": strengths[0][:80], "size": "xxs",
                     "color": "#27500A", "wrap": True, "flex": 5},
                ],
                "spacing": "sm",
                "margin": "md",
                "backgroundColor": "#EAF3DE",
                "cornerRadius": "md",
                "paddingAll": "8px",
            })
        if weaknesses:
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "Weak", "size": "xxs", "color": "#791F1F",
                     "weight": "bold", "flex": 0},
                    {"type": "text", "text": weaknesses[0][:80], "size": "xxs",
                     "color": "#791F1F", "wrap": True, "flex": 5},
                ],
                "spacing": "sm",
                "margin": "sm",
                "backgroundColor": "#FCEBEB",
                "cornerRadius": "md",
                "paddingAll": "8px",
            })

        # Protocol impact
        impact = deep.get("protocol_impact", {})
        proposed = impact.get("proposed_change", "")
        if proposed:
            body_contents.append({
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "對我們科的影響", "size": "xxs",
                     "color": "#0C447C", "weight": "bold"},
                    {"type": "text", "text": proposed[:120], "size": "xxs",
                     "color": "#0C447C", "wrap": True, "margin": "xs"},
                ],
                "margin": "md",
                "backgroundColor": "#E6F1FB",
                "cornerRadius": "md",
                "paddingAll": "8px",
            })
    else:
        # Fallback: Haiku summary
        if summary.get("findings"):
            body_contents.append({"type": "separator", "margin": "lg"})
            body_contents.append({
                "type": "text",
                "text": f"主要發現：{summary['findings'][:150]}",
                "size": "xs",
                "color": "#555555",
                "wrap": True,
                "margin": "md",
            })

    # Footer: feedback buttons + links
    footer_contents = [
        # Feedback buttons row
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                _feedback_button("Must read", pmid, "#3C3489"),
                _feedback_button("Useful", pmid, "#085041"),
                _feedback_button("So-so", pmid, "#5F5E5A"),
                _feedback_button("Skip", pmid, "#791F1F"),
            ],
            "spacing": "xs",
        },
        # PubMed link
        {
            "type": "button",
            "action": {
                "type": "uri",
                "label": "PubMed →",
                "uri": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            },
            "style": "link",
            "height": "sm",
            "color": "#1B6B93",
        },
    ]

    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "paddingAll": "16px",
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": footer_contents,
            "paddingAll": "12px",
            "spacing": "sm",
        },
    }


def _summary_article_bubble(article: dict) -> Optional[dict]:
    """Build a bubble for Score 2-3 article with Haiku summary."""
    score = article.get("total_score", 0)
    summary = article.get("summary", {})
    pmid = article.get("pmid", "")
    badge_bg, badge_color = _score_color(score)

    body_contents = [
        # Tags
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": f"Score {score}", "size": "xxs",
                 "color": badge_color, "weight": "bold", "flex": 0},
                {"type": "text", "text": article.get("source_journal", ""),
                 "size": "xxs", "color": "#888888", "flex": 0},
            ],
            "spacing": "sm",
        },
        # Title
        {
            "type": "text",
            "text": article["title"][:100] + ("..." if len(article["title"]) > 100 else ""),
            "weight": "bold",
            "size": "sm",
            "wrap": True,
            "maxLines": 3,
            "margin": "md",
        },
        # Summary
        {"type": "separator", "margin": "lg"},
    ]

    if summary.get("purpose"):
        body_contents.append({
            "type": "text",
            "text": f"研究目的：{summary['purpose'][:100]}",
            "size": "xs", "color": "#555555", "wrap": True, "margin": "md",
        })
    if summary.get("findings"):
        body_contents.append({
            "type": "text",
            "text": f"主要發現：{summary['findings'][:120]}",
            "size": "xs", "color": "#555555", "wrap": True, "margin": "sm",
        })
    if summary.get("significance"):
        body_contents.append({
            "type": "text",
            "text": f"臨床意義：{summary['significance'][:100]}",
            "size": "xs", "color": "#555555", "wrap": True, "margin": "sm",
        })

    footer_contents = [
        # Feedback row
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                _feedback_button("Must read", pmid, "#3C3489"),
                _feedback_button("Useful", pmid, "#085041"),
                _feedback_button("So-so", pmid, "#5F5E5A"),
                _feedback_button("Skip", pmid, "#791F1F"),
            ],
            "spacing": "xs",
        },
        # Deep analysis + PubMed row
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "Deep analysis →",
                        "data": f"action=deep_analysis&pmid={pmid}",
                        "displayText": f"Requesting deep analysis for PMID {pmid}...",
                    },
                    "style": "link",
                    "height": "sm",
                    "color": "#3C3489",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "PubMed →",
                        "uri": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    },
                    "style": "link",
                    "height": "sm",
                    "color": "#1B6B93",
                },
            ],
            "spacing": "none",
        },
    ]

    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "paddingAll": "16px",
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": footer_contents,
            "paddingAll": "12px",
            "spacing": "sm",
        },
    }


def _feedback_button(label: str, pmid: str, color: str) -> dict:
    return {
        "type": "button",
        "action": {
            "type": "postback",
            "label": label,
            "data": f"action=feedback&pmid={pmid}&rating={label.lower().replace(' ', '_')}",
            "displayText": f"{label}",
        },
        "style": "link",
        "height": "sm",
        "color": color,
        "flex": 1,
    }
