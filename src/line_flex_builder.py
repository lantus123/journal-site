"""
LINE Flex Message builder.
Only used for Score 5 instant alerts — single article Flex bubble.
Daily digest is now a text message with web link (see push_line.py).
"""

from typing import Optional


def build_single_article_flex(article: dict) -> Optional[dict]:
    """Build a single Flex Message bubble for Score 5 instant alert."""
    score = article.get("total_score", 0)
    deep = article.get("deep_analysis", {})
    pmid = article.get("pmid", "")

    badge_bg, badge_color = "#EEEDFE", "#3C3489"

    body_contents = [
        # Score badge + journal
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
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

        # Strong point
        meth = deep.get("methodology_audit", {})
        strengths = meth.get("strengths", [])
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

        # Weak point
        weaknesses = meth.get("weaknesses", [])
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

    # Footer: PubMed link only
    footer_contents = [
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

    bubble = {
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

    return {
        "type": "flex",
        "altText": f"🔔 Must-read: {article['title'][:40]}...",
        "contents": bubble,
    }
