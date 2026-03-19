"""
LINE Flex Message builder.
Converts scored articles into Flex Message JSON for LINE Messaging API.
Focus: Score 4-5 articles with deep analysis in Flex carousel.
"""

import json
from typing import Optional


def build_digest_flex(articles: list[dict], on_demand: list[dict] = None) -> dict:
    """
    Build Flex Message carousel for Score 4-5 + on-demand articles.
    No header bubble — first card is the first article.
    """
    on_demand = on_demand or []
    bubbles = []

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

    if not bubbles:
        return None

    total = len(articles) + len(on_demand)
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
    bubble = _deep_article_bubble(article)
    if not bubble:
        return None
    return {
        "type": "flex",
        "altText": f"[Score {article.get('total_score', '?')}] {article['title'][:40]}...",
        "contents": bubble,
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
    """Build a bubble for an article with deep analysis."""
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
        # Feedback buttons row - using emoji for readability
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                _feedback_button("🔥", "must_read", pmid, "#3C3489"),
                _feedback_button("👍", "useful", pmid, "#085041"),
                _feedback_button("➖", "so_so", pmid, "#5F5E5A"),
                _feedback_button("👎", "skip", pmid, "#791F1F"),
            ],
            "spacing": "sm",
        },
        # Feedback label
        {
            "type": "text",
            "text": "🔥Must read · 👍Useful · ➖So-so · 👎Skip",
            "size": "xxs",
            "color": "#BBBBBB",
            "align": "center",
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


def _feedback_button(label: str, rating: str, pmid: str, color: str) -> dict:
    return {
        "type": "button",
        "action": {
            "type": "postback",
            "label": label,
            "data": f"action=feedback&pmid={pmid}&rating={rating}",
            "displayText": f"{label} ({rating.replace('_', ' ')})",
        },
        "style": "link",
        "height": "sm",
        "color": color,
        "flex": 1,
    }


def build_compact_list_flex(articles: list[dict], high_count: int = 0, on_demand_count: int = 0) -> Optional[dict]:
    """
    Build compact Flex carousel for Score 2-3 articles.
    Packs 2 articles per bubble with feedback buttons.
    """
    if not articles:
        return None

    bubbles = []

    # Pack 2 articles per bubble
    for i in range(0, len(articles), 2):
        chunk = articles[i:i+2]
        body_contents = []

        # Stats header on first bubble only
        if i == 0:
            total = len(articles) + high_count + on_demand_count
            stats = f"NICU Journal Digest · {total} articles today"
            if high_count:
                stats += f" · {high_count} deep ↑"
            body_contents.append({
                "type": "text",
                "text": stats,
                "size": "xxs",
                "color": "#1B6B93",
                "weight": "bold",
            })
            body_contents.append({"type": "separator", "margin": "sm"})

        for j, a in enumerate(chunk):
            if j > 0:
                body_contents.append({"type": "separator", "margin": "lg"})

            score = a.get("total_score", 0)
            pmid = a.get("pmid", "")
            badge_bg, badge_color = _score_color(score)
            summary = a.get("summary", {})
            one_liner = a.get("one_liner", "")

            # Score + journal
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": f"Score {score}", "size": "xxs",
                     "color": badge_color, "weight": "bold", "flex": 0},
                    {"type": "text", "text": a.get("source_journal", ""),
                     "size": "xxs", "color": "#888888", "flex": 0},
                ],
                "spacing": "sm",
                "margin": "md",
            })

            # Title
            body_contents.append({
                "type": "text",
                "text": a.get("title", "")[:90] + ("..." if len(a.get("title", "")) > 90 else ""),
                "weight": "bold",
                "size": "xs",
                "wrap": True,
                "maxLines": 2,
                "margin": "sm",
            })

            # One-liner or significance
            hint = one_liner or summary.get("significance", "") or summary.get("findings", "")
            if hint:
                body_contents.append({
                    "type": "text",
                    "text": f"→ {hint[:80]}",
                    "size": "xxs",
                    "color": "#666666",
                    "wrap": True,
                    "maxLines": 2,
                    "margin": "xs",
                })

            # Feedback + actions row
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    _feedback_button("🔥", "must_read", pmid, "#3C3489"),
                    _feedback_button("👍", "useful", pmid, "#085041"),
                    _feedback_button("➖", "so_so", pmid, "#5F5E5A"),
                    _feedback_button("👎", "skip", pmid, "#791F1F"),
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "🔬",
                            "data": f"action=deep_analysis&pmid={pmid}",
                            "displayText": f"Requesting deep analysis for PMID {pmid}...",
                        },
                        "style": "link",
                        "height": "sm",
                        "color": "#3C3489",
                        "flex": 1,
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "📄",
                            "uri": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        },
                        "style": "link",
                        "height": "sm",
                        "color": "#1B6B93",
                        "flex": 1,
                    },
                ],
                "spacing": "none",
                "margin": "sm",
            })

        bubble = {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_contents,
                "paddingAll": "14px",
            },
        }
        bubbles.append(bubble)

    # Max 12 bubbles
    bubbles = bubbles[:12]

    return {
        "type": "flex",
        "altText": f"NICU Journal Digest - {len(articles)} articles (Score 2-3)",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }
