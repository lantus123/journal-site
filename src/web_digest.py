"""
HTML Digest Generator for GitHub Pages.
Creates daily digest HTML pages and an index page with archive.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))


class WebDigestGenerator:
    """Generate static HTML digest pages for GitHub Pages."""

    def __init__(self, output_dir: str = "docs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, articles: list[dict], on_demand: list[dict] = None):
        """Generate today's digest page and update the index."""
        on_demand = on_demand or []
        today = datetime.now(TW_TZ)
        date_str = today.strftime("%Y-%m-%d")
        display_date = today.strftime("%Y/%m/%d (%A)")

        digest_articles = [a for a in articles if a.get("total_score", 0) >= 2]
        if not digest_articles and not on_demand:
            logger.info("No articles for web digest")
            return

        # Generate daily page
        daily_html = self._build_daily_page(digest_articles, on_demand, date_str, display_date)
        daily_path = self.output_dir / f"{date_str}.html"
        with open(daily_path, "w", encoding="utf-8") as f:
            f.write(daily_html)
        logger.info(f"Daily digest page: {daily_path}")

        # Update index
        self._update_index(date_str, display_date, digest_articles, on_demand)
        logger.info("Index page updated")

    def _build_daily_page(self, articles, on_demand, date_str, display_date):
        high = [a for a in articles if a.get("total_score", 0) >= 4]
        medium = [a for a in articles if 2 <= a.get("total_score", 0) <= 3]
        total = len(high) + len(medium) + len(on_demand)
        must_read = sum(1 for a in articles if a.get("total_score", 0) == 5)

        sections = []

        if on_demand:
            sections.append(self._section_header("REQUESTED BY COLLEAGUE"))
            for a in on_demand:
                sections.append(self._render_article(a, is_deep=True, is_on_demand=True))

        if high:
            sections.append(self._section_header("SCORE 4-5: DEEP ANALYSIS"))
            for a in high:
                sections.append(self._render_article(a, is_deep=True))

        if medium:
            sections.append(self._section_header("SCORE 2-3: QUICK SUMMARY"))
            for a in medium:
                sections.append(self._render_article(a, is_deep=False))

        stats = f"{total} articles"
        if must_read:
            stats += f" · {must_read} must-read"

        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NICU Journal Digest - {date_str}</title>
{self._css()}
</head>
<body>
<div class="container">
<header>
  <a href="index.html" class="back">← Back to archive</a>
  <div class="date">{display_date}</div>
  <h1>NICU Journal Digest</h1>
  <div class="stats">{stats}</div>
</header>
{''.join(sections)}
<footer>
  NICU Journal Auto-Review System · 馬偕紀念醫院新生兒科<br>
  AI scoring by Claude (Haiku + Sonnet)
</footer>
</div>
</body>
</html>"""

    def _update_index(self, date_str, display_date, articles, on_demand):
        """Update index.html with link to today's digest."""
        archive_path = self.output_dir / "archive.json"
        archive = []
        if archive_path.exists():
            with open(archive_path) as f:
                archive = json.load(f)

        total = len([a for a in articles if a.get("total_score", 0) >= 2]) + len(on_demand)
        must_read = sum(1 for a in articles if a.get("total_score", 0) == 5)
        deep = sum(1 for a in articles if a.get("total_score", 0) >= 4)

        entry = {
            "date": date_str,
            "display_date": display_date,
            "total": total,
            "must_read": must_read,
            "deep_analysis": deep,
            "top_article": "",
        }

        top = [a for a in articles if a.get("total_score", 0) >= 4]
        if top:
            entry["top_article"] = top[0].get("title", "")[:80]

        # Remove existing entry for today if re-running
        archive = [e for e in archive if e["date"] != date_str]
        archive.insert(0, entry)
        # Keep last 365 days
        archive = archive[:365]

        with open(archive_path, "w") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)

        # Generate index.html
        index_html = self._build_index(archive, date_str)
        with open(self.output_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(index_html)

    def _build_index(self, archive, latest_date):
        rows = ""
        for entry in archive:
            must_badge = ""
            if entry.get("must_read", 0) > 0:
                must_badge = f'<span class="badge badge-must">{entry["must_read"]} must-read</span>'
            deep_badge = ""
            if entry.get("deep_analysis", 0) > 0:
                deep_badge = f'<span class="badge badge-deep">{entry["deep_analysis"]} deep</span>'

            top = entry.get("top_article", "")
            if top:
                top = f'<div class="top-article">{top}...</div>'

            rows += f"""
<a href="{entry['date']}.html" class="archive-row">
  <div class="archive-date">{entry['display_date']}</div>
  <div class="archive-info">
    <span class="archive-count">{entry['total']} articles</span>
    {must_badge}{deep_badge}
    {top}
  </div>
</a>"""

        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NICU Journal Digest - Archive</title>
{self._css()}
<style>
.archive-row{{display:block;padding:16px;border:1px solid #e0e0e0;border-radius:12px;margin-bottom:10px;text-decoration:none;color:inherit;transition:border-color .15s}}
.archive-row:hover{{border-color:#1B6B93}}
.archive-date{{font-size:14px;font-weight:600;color:#1B6B93;margin-bottom:4px}}
.archive-info{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.archive-count{{font-size:13px;color:#666}}
.badge{{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
.badge-must{{background:#EEEDFE;color:#3C3489}}
.badge-deep{{background:#E1F5EE;color:#085041}}
.top-article{{font-size:12px;color:#999;width:100%;margin-top:4px}}
.hero{{padding:24px 0;margin-bottom:20px}}
.hero h1{{font-size:28px;font-weight:700;color:#1B6B93;margin:0 0 8px}}
.hero p{{font-size:14px;color:#888;margin:0}}
</style>
</head>
<body>
<div class="container">
<div class="hero">
  <h1>NICU Journal Digest</h1>
  <p>馬偕紀念醫院新生兒科 · AI-powered daily literature review</p>
  <p style="margin-top:8px;font-size:13px;color:#aaa;">Tracking {len(archive)} days of neonatal literature</p>
</div>

{rows if rows else '<p style="color:#999;text-align:center;padding:40px;">No digests yet. Check back tomorrow morning!</p>'}

<footer>
  NICU Journal Auto-Review System · AI scoring by Claude (Haiku + Sonnet)
</footer>
</div>
</body>
</html>"""

    def _section_header(self, title):
        return f"""
<div style="display:flex;align-items:center;gap:10px;margin:28px 0 14px;">
  <div style="flex:1;height:1px;background:#ddd;"></div>
  <div style="font-size:12px;font-weight:600;color:#1B6B93;letter-spacing:0.5px;">{title}</div>
  <div style="flex:1;height:1px;background:#ddd;"></div>
</div>"""

    def _render_article(self, article, is_deep=False, is_on_demand=False):
        score = article.get("total_score", 0)
        deep = article.get("deep_analysis", {})
        summary = article.get("summary", {})
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")

        # Score colors
        if score >= 5:
            badge_bg, badge_color = "#EEEDFE", "#3C3489"
        elif score >= 4:
            badge_bg, badge_color = "#E1F5EE", "#085041"
        else:
            badge_bg, badge_color = "#F1EFE8", "#5F5E5A"

        tags = f'<span class="tag" style="background:{badge_bg};color:{badge_color}">Score {score}</span>'
        tags += f'<span class="tag-journal">{article.get("source_journal", "")}</span>'
        if is_deep and deep:
            tags += '<span class="tag" style="background:#FAECE7;color:#712B13">Sonnet deep analysis</span>'
        if article.get("is_oa"):
            tags += '<span class="tag" style="background:#EAF3DE;color:#27500A">OA</span>'
        if is_on_demand:
            tags += '<span class="tag" style="background:#E6F1FB;color:#0C447C">Requested by colleague</span>'

        # Content
        content = ""
        if is_deep and deep:
            # 30-sec summary
            thirty = deep.get("thirty_second_summary", "")
            if thirty:
                content += f'<div class="section"><b>30 秒重點：</b>{thirty}</div>'

            # Hidden findings
            hidden = deep.get("hidden_findings", [])
            if hidden:
                items = "".join(f"<p><b>{h.get('finding','')}</b> {h.get('source','')}。{h.get('implication','')}</p>" for h in hidden)
                content += f'<div class="section"><div class="section-label" style="color:#712B13">Abstract 沒告訴你的事</div>{items}</div>'

            # Methodology
            meth = deep.get("methodology_audit", {})
            if meth:
                meth_html = ""
                for s in meth.get("strengths", []):
                    meth_html += f'<div class="hl hl-green"><b>Strong：</b>{s}</div>'
                for n in meth.get("notes", []):
                    meth_html += f'<div class="hl hl-amber"><b>Note：</b>{n}</div>'
                for w in meth.get("weaknesses", []):
                    meth_html += f'<div class="hl hl-red"><b>Weak：</b>{w}</div>'
                if meth_html:
                    content += f'<div class="section"><div class="section-label" style="color:#633806">方法學評估</div>{meth_html}</div>'

            # Evidence positioning
            evidence = deep.get("evidence_positioning", {})
            related = evidence.get("related_studies", [])
            if related:
                rel_html = ""
                for r in related:
                    rel_html += f'<div class="related"><b>{r.get("citation","")}</b> — {r.get("comparison","")}</div>'
                guideline = evidence.get("guideline_status", "")
                gap = evidence.get("evidence_gap_filled", "")
                ongoing = evidence.get("ongoing_trials", "")
                extra = ""
                if guideline:
                    extra += f"<p><b>指引現況：</b>{guideline}</p>"
                if gap:
                    extra += f"<p><b>填補的 evidence gap：</b>{gap}</p>"
                if ongoing:
                    extra += f"<p><b>進行中的相關試驗：</b>{ongoing}</p>"
                content += f'<div class="section"><div class="section-label" style="color:#3C3489">與現有證據的定位</div>{rel_html}{extra}</div>'

            # Protocol impact
            impact = deep.get("protocol_impact", {})
            if impact:
                current = impact.get("current_practice", "")
                proposed = impact.get("proposed_change", "")
                missing = impact.get("missing_evidence", "")
                prereqs = impact.get("prerequisites", [])
                impact_html = '<div class="hl hl-blue">'
                if current:
                    impact_html += f"<b>目前做法：</b>{current}<br>"
                if proposed:
                    impact_html += f"<b>建議調整：</b>{proposed}<br>"
                if prereqs:
                    impact_html += f"<b>導入準備：</b>{', '.join(prereqs)}<br>"
                if missing:
                    impact_html += f"<b>等待的證據：</b>{missing}"
                impact_html += "</div>"
                content += f'<div class="section"><div class="section-label" style="color:#085041">對我們科的具體影響</div>{impact_html}</div>'
        else:
            # Haiku summary
            s = summary
            if s:
                content += '<div class="section">'
                if s.get("purpose"):
                    content += f'<p><b>研究目的：</b>{s["purpose"]}</p>'
                if s.get("design"):
                    content += f'<p><b>研究設計：</b>{s["design"]}</p>'
                if s.get("findings"):
                    content += f'<p><b>主要發現：</b>{s["findings"]}</p>'
                if s.get("significance"):
                    content += f'<p><b>臨床意義：</b>{s["significance"]}</p>'
                content += '</div>'

        # Links
        links = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank">PubMed →</a>'
        if doi:
            links += f' <a href="https://doi.org/{doi}" target="_blank">DOI →</a>'
        if article.get("oa_url"):
            links += f' <a href="{article["oa_url"]}" target="_blank">Full text (OA) →</a>'

        return f"""
<div class="card">
  <div class="card-tags">{tags}</div>
  <h2 class="card-title">{article.get('title', '')}</h2>
  <div class="card-authors">{article.get('authors', '')} · {article.get('pub_date', '')}</div>
  {content}
  <div class="card-links">{links}</div>
</div>"""

    def _css(self):
        return """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Noto Sans TC',sans-serif;background:#f7f7f3;color:#333;line-height:1.7}
.container{max-width:720px;margin:0 auto;padding:20px}
header{padding:20px 0;border-bottom:2px solid #1B6B93;margin-bottom:24px}
.back{font-size:13px;color:#1B6B93;text-decoration:none}
.back:hover{text-decoration:underline}
.date{font-size:13px;color:#888;margin-top:8px}
h1{font-size:24px;font-weight:700;color:#1B6B93;margin-top:4px}
.stats{font-size:13px;color:#666;margin-top:6px}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:18px;margin-bottom:16px}
.card-tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tag{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.tag-journal{font-size:11px;color:#999}
.card-title{font-size:16px;font-weight:600;color:#222;line-height:1.4;margin-bottom:6px}
.card-authors{font-size:12px;color:#999;margin-bottom:12px}
.section{padding:12px 0;border-top:1px solid #f0f0ec}
.section p{font-size:13px;color:#555;margin-bottom:6px}
.section-label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:8px}
.hl{border-left:3px solid;padding:8px 12px;margin:6px 0;font-size:13px;line-height:1.6;border-radius:0}
.hl-green{border-color:#639922;background:#EAF3DE;color:#27500A}
.hl-amber{border-color:#BA7517;background:#FAEEDA;color:#633806}
.hl-red{border-color:#E24B4A;background:#FCEBEB;color:#791F1F}
.hl-blue{border-color:#378ADD;background:#E6F1FB;color:#0C447C}
.related{font-size:13px;color:#555;padding:6px 0;border-bottom:1px solid #f5f5f0}
.related:last-child{border-bottom:none}
.card-links{padding-top:12px;display:flex;gap:16px}
.card-links a{font-size:12px;color:#1B6B93;text-decoration:none}
.card-links a:hover{text-decoration:underline}
footer{padding:24px 0;margin-top:32px;border-top:1px solid #ddd;font-size:11px;color:#999;text-align:center}
@media(max-width:600px){.container{padding:12px}.card{padding:14px}}
</style>"""
