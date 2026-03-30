"""
LINE Flex Message builder.
- Daily digest: carousel of article cards + summary header
- Score 5: single article Flex bubble for instant alert
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


def _get_hook_text(article: dict) -> str:
    """Extract the best one-liner hook from an article for LINE display."""
    deep = article.get("deep_analysis", {})
    summary = article.get("summary", {})

    # Prefer 30-sec summary for high-score articles
    if deep:
        thirty = deep.get("thirty_second_summary", "")
        if thirty:
            return thirty[:120] + ("..." if len(thirty) > 120 else "")

    # Fall back to findings from haiku summary
    if summary:
        findings = summary.get("findings", "")
        if findings:
            return findings[:120] + ("..." if len(findings) > 120 else "")
        significance = summary.get("significance", "")
        if significance:
            return significance[:120] + ("..." if len(significance) > 120 else "")

    return ""


def _article_bubble(article: dict, is_on_demand: bool = False) -> dict:
    """Build a compact bubble for one article in the digest carousel."""
    score = article.get("total_score", 0)
    journal = article.get("source_journal", "")
    title = article.get("title", "")
    hook = _get_hook_text(article)

    # Score badge color
    if score >= 5:
        badge_color = "#3C3489"
        badge_bg = "#EEEDFE"
    elif score >= 4:
        badge_color = "#085041"
        badge_bg = "#E1F5EE"
    else:
        badge_color = "#5F5E5A"
        badge_bg = "#F1EFE8"

    # Tags row
    tags = [
        {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"Score {score}", "size": "xxs",
                 "color": badge_color, "weight": "bold", "align": "center"},
            ],
            "backgroundColor": badge_bg,
            "cornerRadius": "sm",
            "paddingAll": "4px",
            "width": "52px",
        },
        {"type": "text", "text": journal, "size": "xxs", "color": "#888888",
         "flex": 1, "gravity": "center"},
    ]
    if is_on_demand:
        tags.insert(1, {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "Requested", "size": "xxs",
                 "color": "#0C447C", "weight": "bold", "align": "center"},
            ],
            "backgroundColor": "#E6F1FB",
            "cornerRadius": "sm",
            "paddingAll": "4px",
            "width": "64px",
        })

    body_contents = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": tags,
            "spacing": "sm",
        },
        # Title
        {
            "type": "text",
            "text": title[:100] + ("..." if len(title) > 100 else ""),
            "weight": "bold",
            "size": "sm",
            "wrap": True,
            "maxLines": 3,
            "margin": "md",
        },
    ]

    # Hook text — the key to making people want to click
    if hook:
        body_contents.append({
            "type": "text",
            "text": f"💡 {hook}",
            "size": "xs",
            "color": "#555555",
            "wrap": True,
            "maxLines": 4,
            "margin": "md",
        })

    # Protocol impact for score 4-5
    deep = article.get("deep_analysis", {})
    if deep:
        impact = deep.get("protocol_impact", {})
        proposed = impact.get("proposed_change", "")
        if proposed:
            body_contents.append({
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"🏥 {proposed[:80]}",
                     "size": "xxs", "color": "#0C447C", "wrap": True},
                ],
                "margin": "md",
                "backgroundColor": "#E6F1FB",
                "cornerRadius": "md",
                "paddingAll": "8px",
            })

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "paddingAll": "16px",
            "spacing": "none",
        },
    }


def build_digest_flex(
    articles: list[dict],
    on_demand: list[dict],
    display_date: str,
    web_url: str,
    dept_short: str = "NB",
) -> Optional[dict]:
    """Build a Flex Message carousel for the daily digest.

    Structure:
    - First bubble: summary header with stats + CTA button
    - Following bubbles: one per article (score 4-5 with hook, score 2-3 compact)
    - Last bubble: "View all" CTA if there are more articles
    LINE carousel limit: 12 bubbles.
    """
    high = [a for a in articles if a.get("total_score", 0) >= 4]
    medium = [a for a in articles if 2 <= a.get("total_score", 0) <= 3]
    total = len(high) + len(medium) + len(on_demand)

    if total == 0:
        return None

    must_read = sum(1 for a in articles if a.get("total_score", 0) == 5)

    # --- Header bubble ---
    stats_items = [
        {"type": "text", "text": f"共 {total} 篇文章", "size": "sm",
         "color": "#555555", "margin": "md"},
    ]
    if must_read:
        stats_items.append(
            {"type": "text", "text": f"🔔 {must_read} 篇 Must-read", "size": "sm",
             "color": "#3C3489", "weight": "bold", "margin": "sm"},
        )
    if len(high):
        stats_items.append(
            {"type": "text", "text": f"⭐ {len(high)} 篇深度分析（Score 4-5）",
             "size": "xs", "color": "#666666", "margin": "sm"},
        )
    if len(medium):
        stats_items.append(
            {"type": "text", "text": f"📋 {len(medium)} 篇快速摘要（Score 2-3）",
             "size": "xs", "color": "#666666", "margin": "sm"},
        )
    if on_demand:
        stats_items.append(
            {"type": "text", "text": f"🔬 {len(on_demand)} 篇同事指定分析",
             "size": "xs", "color": "#666666", "margin": "sm"},
        )

    # Teaser: show the top article hook in the header
    top_hook = ""
    if high:
        top_hook = _get_hook_text(high[0])
    elif on_demand:
        top_hook = _get_hook_text(on_demand[0])
    if top_hook:
        stats_items.append({"type": "separator", "margin": "lg"})
        stats_items.append(
            {"type": "text", "text": f"📌 {top_hook}", "size": "xs",
             "color": "#1B6B93", "wrap": True, "maxLines": 3, "margin": "md"},
        )

    header_bubble = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"{dept_short} Journal Digest",
                 "weight": "bold", "size": "lg", "color": "#1B6B93"},
                {"type": "text", "text": display_date, "size": "xs",
                 "color": "#999999", "margin": "xs"},
                *stats_items,
            ],
            "paddingAll": "20px",
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "查看完整分析 →",
                        "uri": web_url,
                    },
                    "style": "primary",
                    "color": "#1B6B93",
                    "height": "sm",
                },
            ],
            "paddingAll": "12px",
        },
    }

    bubbles = [header_bubble]

    # --- Article bubbles (max 10 to stay within 12-bubble limit) ---
    # Priority: on-demand first, then high score, then medium
    article_slots = 10
    for a in on_demand[:article_slots]:
        bubbles.append(_article_bubble(a, is_on_demand=True))
    remaining = article_slots - len(on_demand)

    for a in high[:remaining]:
        bubbles.append(_article_bubble(a))
    remaining -= min(len(high), remaining)

    for a in medium[:remaining]:
        bubbles.append(_article_bubble(a))
    remaining -= min(len(medium), remaining)

    # --- Tail CTA bubble if articles were truncated ---
    shown = len(bubbles) - 1  # minus header
    if shown < total:
        bubbles.append({
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"還有 {total - shown} 篇文章",
                     "size": "sm", "color": "#555555", "weight": "bold",
                     "align": "center", "margin": "lg"},
                    {"type": "text", "text": "點擊下方按鈕查看完整內容",
                     "size": "xs", "color": "#999999", "align": "center",
                     "margin": "md"},
                ],
                "paddingAll": "20px",
                "justifyContent": "center",
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "查看全部 →",
                            "uri": web_url,
                        },
                        "style": "primary",
                        "color": "#1B6B93",
                        "height": "sm",
                    },
                ],
                "paddingAll": "12px",
            },
        })

    # LINE carousel max 12 bubbles
    bubbles = bubbles[:12]

    return {
        "type": "flex",
        "altText": f"📰 {dept_short} Journal Digest {display_date} - {total} 篇文章",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }
