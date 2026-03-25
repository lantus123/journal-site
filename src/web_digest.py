"""
HTML Digest Generator for GitHub Pages.
Creates daily digest HTML pages and an index page with archive.
Features: password + token gate, JSONP feedback buttons, localStorage voting memory.
"""

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))


DEPT_NAMES = {
    "newborn": "NICU Journal Digest",
    "cardiology": "Pediatric Cardiology Digest",
}

DEPT_SUBTITLES = {
    "newborn": "馬偕紀念醫院新生兒科 · AI-powered daily literature review",
    "cardiology": "馬偕紀念醫院小兒心臟科 · AI-powered daily literature review",
}


class WebDigestGenerator:
    """Generate static HTML digest pages for GitHub Pages."""

    def __init__(self, dept: str = "newborn", output_dir: str = None):
        self.dept = dept
        self.dept_name = DEPT_NAMES.get(dept, dept)
        self.dept_subtitle = DEPT_SUBTITLES.get(dept, "")
        self.output_dir = Path(output_dir) if output_dir else Path(f"docs/{dept}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.feedback_url = os.environ.get("FEEDBACK_WEBHOOK_URL", "")
        self.feedback_secret = os.environ.get("FEEDBACK_SECRET", "")
        # Per-department password: DIGEST_PASSWORD_NEWBORN, DIGEST_PASSWORD_CARDIOLOGY
        pw_env = f"DIGEST_PASSWORD_{dept.upper()}"
        self.password = os.environ.get(pw_env, os.environ.get("DIGEST_PASSWORD", ""))
        self.password_hash = ""
        if self.password:
            self.password_hash = hashlib.sha256(self.password.encode()).hexdigest()
        self.scoring_config = self._load_scoring_config()
        self.journals_config = self._load_journals_config()

    def _load_scoring_config(self) -> dict:
        """Load scoring config for display on index page."""
        config_path = Path(f"config/{self.dept}/scoring_config.yaml")
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f)
        return {}

    def _load_pdf_analyses(self) -> set:
        """Load set of PMIDs that have PDF analyses."""
        analyses_dir = Path(f"data/{self.dept}/pdf_analyses")
        if not analyses_dir.exists():
            return set()
        return {p.stem for p in analyses_dir.glob("*.json")}

    def _build_feedback_map(self, feedback: list) -> dict:
        """Build a map of pmid -> {rating: count} from feedback entries."""
        fb_map: dict[str, dict[str, int]] = {}
        for entry in feedback:
            pmid = entry.get("pmid", "")
            rating = entry.get("rating", "")
            if pmid and rating:
                fb_map.setdefault(pmid, {})
                fb_map[pmid][rating] = fb_map[pmid].get(rating, 0) + 1
        return fb_map

    def _load_journals_config(self) -> list:
        """Load journals config for display on index page."""
        config_path = Path(f"config/{self.dept}/journals.yaml")
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f).get("journals", [])
        return []

    def generate(self, articles: list[dict], on_demand: list[dict] = None, override_date: str = None):
        """Generate today's digest page and update the index.

        Args:
            override_date: Optional YYYY-MM-DD string to generate for a past date (backfill).
        """
        on_demand = on_demand or []
        if override_date:
            dt = datetime.strptime(override_date, "%Y-%m-%d")
            date_str = override_date
            display_date = dt.strftime("%Y/%m/%d (%A)")
        else:
            today = datetime.now(TW_TZ)
            date_str = today.strftime("%Y-%m-%d")
            display_date = today.strftime("%Y/%m/%d (%A)")

        digest_articles = [a for a in articles if a.get("total_score", 0) >= 2]
        if not digest_articles and not on_demand:
            logger.info("No articles for web digest")
            return

        # Load feedback summaries
        from .feedback import load_feedback
        all_feedback = load_feedback(dept=self.dept)
        self.feedback_map = self._build_feedback_map(all_feedback)

        # Load existing PDF analyses
        self.pdf_analyses = self._load_pdf_analyses()

        # Generate a daily token
        token = secrets.token_hex(4)  # 8-char hex
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Generate daily page
        daily_html = self._build_daily_page(
            digest_articles, on_demand, date_str, display_date, token_hash
        )
        daily_path = self.output_dir / f"{date_str}.html"
        with open(daily_path, "w", encoding="utf-8") as f:
            f.write(daily_html)
        logger.info(f"Daily digest page: {daily_path}")

        # Update index
        self._update_index(date_str, display_date, digest_articles, on_demand, token)
        logger.info("Index page updated")

    def regenerate_index(self):
        """Regenerate index.html from existing archive.json without creating a new daily page."""
        archive_path = Path(f"data/{self.dept}/archive.json")
        if not archive_path.exists():
            logger.info("No archive.json found, skipping index regeneration")
            return
        with open(archive_path) as f:
            archive = json.load(f)
        index_html = self._build_index(archive)
        with open(self.output_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(index_html)
        logger.info("Index page regenerated from existing archive")

    def _auth_gate_js(self, token_hash: str) -> str:
        """JavaScript for password + token authentication gate."""
        return f"""<script>
(function() {{
  var TOKEN_HASH = "{token_hash}";
  var PW_HASH = "{self.password_hash}";
  var content = document.getElementById('digest-content');
  var gate = document.getElementById('auth-gate');

  function sha256(str) {{
    var encoder = new TextEncoder();
    return crypto.subtle.digest('SHA-256', encoder.encode(str)).then(function(buf) {{
      return Array.from(new Uint8Array(buf)).map(function(b) {{
        return b.toString(16).padStart(2, '0');
      }}).join('');
    }});
  }}

  function unlock() {{
    gate.style.display = 'none';
    content.style.display = 'block';
  }}

  function checkAccess() {{
    // 1. Check URL token
    var params = new URLSearchParams(window.location.search);
    var t = params.get('t');
    if (t && TOKEN_HASH) {{
      sha256(t).then(function(h) {{
        if (h === TOKEN_HASH) {{
          localStorage.setItem('digest_token', t);
          unlock();
        }} else {{
          checkPassword();
        }}
      }});
      return;
    }}

    // 2. Check stored password
    checkPassword();
  }}

  function checkPassword() {{
    if (!PW_HASH) {{ unlock(); return; }}
    var saved = localStorage.getItem('digest_pw');
    if (saved) {{
      sha256(saved).then(function(h) {{
        if (h === PW_HASH) {{ unlock(); }}
        else {{ gate.style.display = 'flex'; }}
      }});
    }} else {{
      gate.style.display = 'flex';
    }}
  }}

  window.submitPassword = function() {{
    var input = document.getElementById('pw-input').value;
    sha256(input).then(function(h) {{
      if (h === PW_HASH) {{
        localStorage.setItem('digest_pw', input);
        unlock();
      }} else {{
        document.getElementById('pw-error').style.display = 'block';
      }}
    }});
  }};

  document.addEventListener('DOMContentLoaded', checkAccess);
}})();
</script>"""

    def _feedback_js(self) -> str:
        """JavaScript for JSONP feedback buttons with localStorage memory."""
        if not self.feedback_url:
            return ""
        return f"""<script>
(function() {{
  var FEEDBACK_URL = "{self.feedback_url}";
  var SECRET = "{self.feedback_secret}";
  var DEPT = "{self.dept}";
  var voted = JSON.parse(localStorage.getItem('digest_voted') || '{{}}'  );

  window.addEventListener('DOMContentLoaded', function() {{
    // Restore previous votes
    Object.keys(voted).forEach(function(pmid) {{
      var btns = document.querySelectorAll('[data-pmid="' + pmid + '"]');
      btns.forEach(function(btn) {{
        btn.style.opacity = '0.4';
        btn.style.pointerEvents = 'none';
      }});
      var label = document.getElementById('voted-' + pmid);
      if (label) {{
        var labels = {{"must_read":"🔥 Must read","useful":"👍 Useful","so_so":"➖ So-so","skip":"👎 Skip"}};
        label.textContent = "Voted: " + (labels[voted[pmid]] || voted[pmid]) + " ✓";
        label.style.display = 'block';
      }}
    }});
  }});

  window.vote = function(pmid, rating, el) {{
    if (voted[pmid]) return;

    // Get uid from token or anonymous
    var uid = 'web_anon';
    var t = new URLSearchParams(window.location.search).get('t');
    if (t) uid = 'web_' + t.substring(0, 8);

    // JSONP call
    var script = document.createElement('script');
    var cb = 'fb_' + Date.now();
    window[cb] = function(resp) {{
      if (resp && resp.status === 'ok') {{
        voted[pmid] = rating;
        localStorage.setItem('digest_voted', JSON.stringify(voted));

        var btns = document.querySelectorAll('[data-pmid="' + pmid + '"]');
        btns.forEach(function(btn) {{
          btn.style.opacity = '0.4';
          btn.style.pointerEvents = 'none';
        }});
        el.style.opacity = '1';
        el.style.background = '#1B6B93';
        el.style.color = '#fff';

        // Update vote count
        var cntEl = document.getElementById('cnt-' + pmid + '-' + rating);
        if (cntEl) {{
          var n = parseInt(cntEl.textContent || '0') + 1;
          cntEl.textContent = n;
          cntEl.style.display = '';
          cntEl.style.color = '#fff';
        }}

        var label = document.getElementById('voted-' + pmid);
        if (label) {{
          var labels = {{"must_read":"🔥 Must read","useful":"👍 Useful","so_so":"➖ So-so","skip":"👎 Skip"}};
          label.textContent = "Voted: " + (labels[rating] || rating) + " ✓";
          label.style.display = 'block';
        }}
      }}
      delete window[cb];
      script.remove();
    }};
    script.src = FEEDBACK_URL + '?action=feedback&pmid=' + pmid + '&rating=' + rating +
      '&uid=' + uid + '&source=web&secret=' + SECRET + '&dept=' + DEPT + '&callback=' + cb;
    document.body.appendChild(script);
  }};
}})();
</script>"""

    def _build_daily_page(self, articles, on_demand, date_str, display_date, token_hash):
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
<title>{self.dept_name} - {date_str}</title>
{self._css()}
</head>
<body>

<!-- Auth gate -->
<div id="auth-gate" style="display:none;justify-content:center;align-items:center;min-height:100vh;background:#f7f7f3;">
<div style="background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.08);max-width:380px;width:90%;">
  <h2 style="color:#1B6B93;margin:0 0 8px;">{self.dept_name}</h2>
  <p style="color:#888;font-size:13px;margin:0 0 24px;">{self.dept_subtitle.split(' · ')[0]}</p>
  <input id="pw-input" type="password" placeholder="請輸入密碼" onkeydown="if(event.key==='Enter')submitPassword()"
    style="width:100%;padding:10px 14px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;margin-bottom:12px;">
  <button onclick="submitPassword()"
    style="width:100%;padding:10px;background:#1B6B93;color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer;">進入</button>
  <p id="pw-error" style="display:none;color:#E24B4A;font-size:13px;margin-top:10px;">密碼錯誤，請重新輸入</p>
  <p style="color:#bbb;font-size:12px;margin-top:16px;">或從 LINE / Email 點擊連結直接閱讀</p>
</div>
</div>

<!-- Digest content (hidden until auth) -->
<div id="digest-content" style="display:none;">
<div class="container">
<header>
  <a href="index.html" class="back">← Back to archive</a>
  <div class="date">{display_date}</div>
  <h1>{self.dept_name}</h1>
  <div class="stats">{stats}</div>
</header>
{''.join(sections)}
<footer>
  Journal Auto-Review System · {self.dept_subtitle.split(' · ')[0]}<br>
  AI scoring by Claude (Haiku + Sonnet)
</footer>
</div>
</div>

{self._auth_gate_js(token_hash)}
{self._feedback_js()}
{self._upload_js()}
</body>
</html>"""

    def _update_index(self, date_str, display_date, articles, on_demand, token):
        """Update index.html with link to today's digest."""
        archive_path = Path(f"data/{self.dept}/archive.json")
        archive = []
        if archive_path.exists():
            with open(archive_path) as f:
                archive = json.load(f)

        total = len([a for a in articles if a.get("total_score", 0) >= 2]) + len(on_demand)
        must_read = sum(1 for a in articles if a.get("total_score", 0) == 5)
        deep = sum(1 for a in articles if a.get("total_score", 0) >= 4)

        # Count votes for today's articles
        fb_map = getattr(self, "feedback_map", {})
        all_pmids = [a.get("pmid", "") for a in articles] + [a.get("pmid", "") for a in on_demand]
        vote_count = sum(sum(fb_map.get(pmid, {}).values()) for pmid in all_pmids if pmid)

        entry = {
            "date": date_str,
            "display_date": display_date,
            "total": total,
            "must_read": must_read,
            "deep_analysis": deep,
            "top_article": "",
            "token": token,
            "votes": vote_count,
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
        index_html = self._build_index(archive)
        with open(self.output_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(index_html)

    def _build_index(self, archive):
        rows = ""
        for entry in archive:
            must_badge = ""
            if entry.get("must_read", 0) > 0:
                must_badge = f'<span class="badge badge-must">{entry["must_read"]} must-read</span>'
            deep_badge = ""
            if entry.get("deep_analysis", 0) > 0:
                deep_badge = f'<span class="badge badge-deep">{entry["deep_analysis"]} deep</span>'

            votes = entry.get("votes", 0)
            vote_badge = ""
            if votes > 0:
                vote_badge = f'<span class="badge badge-vote">💬 {votes} votes</span>'

            top = entry.get("top_article", "")
            if top:
                top = f'<div class="top-article">{top}...</div>'

            # Link includes token if available
            token = entry.get("token", "")
            href = f"{entry['date']}.html"
            if token:
                href += f"?t={token}"

            rows += f"""
<a href="{href}" class="archive-row">
  <div class="archive-date">{entry['display_date']}</div>
  <div class="archive-info">
    <span class="archive-count">{entry['total']} articles</span>
    {must_badge}{deep_badge}{vote_badge}
    {top}
  </div>
</a>"""

        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{self.dept_name} - Archive</title>
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
.badge-vote{{background:#FFF3E0;color:#E65100}}
.top-article{{font-size:12px;color:#999;width:100%;margin-top:4px}}
.hero{{padding:24px 0;margin-bottom:20px}}
.hero h1{{font-size:28px;font-weight:700;color:#1B6B93;margin:0 0 8px}}
.hero p{{font-size:14px;color:#888;margin:0}}
</style>
</head>
<body>

<!-- Auth gate -->
<div id="auth-gate" style="display:none;justify-content:center;align-items:center;min-height:100vh;background:#f7f7f3;">
<div style="background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.08);max-width:380px;width:90%;">
  <h2 style="color:#1B6B93;margin:0 0 8px;">{self.dept_name}</h2>
  <p style="color:#888;font-size:13px;margin:0 0 24px;">{self.dept_subtitle.split(' · ')[0]}</p>
  <input id="pw-input" type="password" placeholder="請輸入密碼" onkeydown="if(event.key==='Enter')submitPassword()"
    style="width:100%;padding:10px 14px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;margin-bottom:12px;">
  <button onclick="submitPassword()"
    style="width:100%;padding:10px;background:#1B6B93;color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer;">進入</button>
  <p id="pw-error" style="display:none;color:#E24B4A;font-size:13px;margin-top:10px;">密碼錯誤，請重新輸入</p>
  <p style="color:#bbb;font-size:12px;margin-top:16px;">密碼請洽科內同仁</p>
</div>
</div>

<!-- Index content -->
<div id="digest-content" style="display:none;">
<div class="container">
<div class="hero">
  <h1>{self.dept_name}</h1>
  <p>{self.dept_subtitle}</p>
  <p style="margin-top:8px;font-size:13px;color:#aaa;">Tracking {len(archive)} days of literature</p>
</div>

{self._scoring_info_html()}
{self._journals_info_html()}

{rows if rows else '<p style="color:#999;text-align:center;padding:40px;">No digests yet. Check back tomorrow morning!</p>'}

<footer>
  Journal Auto-Review System · AI scoring by Claude (Haiku + Sonnet)
</footer>
</div>
</div>

{self._auth_gate_js("")}
</body>
</html>"""

    def _scoring_info_html(self) -> str:
        """Build collapsible scoring methodology section from config."""
        dims = self.scoring_config.get("scoring", {}).get("dimensions", [])
        if_boost = self.scoring_config.get("if_tier_boost", {})
        actions = self.scoring_config.get("actions", {})

        # Dimension icons
        icons = {"design": "📐", "relevance": "🏥", "novelty": "💡", "generalizability": "🌐"}

        dim_rows = ""
        for d in dims:
            icon = icons.get(d["id"], "•")
            pct = int(d["weight"] * 100)
            dim_rows += (
                f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                f'padding:6px 0;border-bottom:1px solid #f0f0ec;">'
                f'<span>{icon} {d["name"]}</span>'
                f'<span style="font-weight:600;color:#1B6B93;">{pct}%</span></div>'
            )

        # IF boost info
        boost_html = ""
        for tier_key, label in [("top_tier", "Top tier"), ("high_tier", "High tier")]:
            tier = if_boost.get(tier_key, {})
            if tier:
                journals = ", ".join(tier.get("journals", []))
                boost_val = tier.get("boost", 0)
                boost_html += (
                    f'<div style="padding:4px 0;font-size:12px;color:#555;">'
                    f'<b>{label} (+{boost_val})：</b>{journals}</div>'
                )

        # Score actions
        action_labels = {
            5: ("🔔", "即時 LINE 推播 + Sonnet 深度分析"),
            4: ("⭐", "Sonnet 深度分析"),
            3: ("📋", "Haiku 快速摘要"),
            2: ("📝", "Haiku 一行摘要"),
            1: ("—", "不列入 digest"),
        }
        action_rows = ""
        for score in [5, 4, 3, 2, 1]:
            icon, desc = action_labels.get(score, ("", ""))
            action_rows += (
                f'<div style="display:flex;gap:8px;padding:3px 0;font-size:12px;color:#555;">'
                f'<span style="font-weight:600;min-width:60px;">Score {score}</span>'
                f'<span>{icon} {desc}</span></div>'
            )

        return f"""
<details style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:0;margin-bottom:20px;">
<summary style="padding:14px 18px;cursor:pointer;font-size:14px;font-weight:600;color:#1B6B93;list-style:none;display:flex;align-items:center;gap:8px;">
  <span style="transition:transform .2s;">▶</span> 評分方式
</summary>
<div style="padding:0 18px 18px;">
  <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:8px;">四維度加權平均（1-5 分）</div>
  {dim_rows}

  <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.3px;margin:16px 0 8px;">期刊 IF 加分（上限 +1）</div>
  {boost_html}

  <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.3px;margin:16px 0 8px;">分數對應動作</div>
  {action_rows}
</div>
</details>
<style>
details[open] summary span:first-child{{transform:rotate(90deg)}}
</style>"""

    def _journals_info_html(self) -> str:
        """Build collapsible monitored journals section from config."""
        journals = self.journals_config
        if not journals:
            return ""

        category_labels = {
            "nicu": ("🏥", "NICU 專科期刊", "全部收錄"),
            "pediatrics": ("👶", "兒科期刊", "關鍵字過濾新生兒相關"),
            "picu": ("🫁", "重症醫學期刊", "關鍵字過濾新生兒相關"),
            "general": ("📚", "綜合頂尖期刊", "關鍵字過濾新生兒相關"),
        }

        # Group by category
        grouped: dict[str, list] = {}
        for j in journals:
            cat = j.get("category", "other")
            grouped.setdefault(cat, []).append(j)

        sections = ""
        for cat in ["nicu", "pediatrics", "picu", "general"]:
            if cat not in grouped:
                continue
            icon, label, note = category_labels.get(cat, ("•", cat, ""))
            names = "、".join(j["name"] for j in grouped[cat])
            sections += (
                f'<div style="padding:8px 0;border-bottom:1px solid #f0f0ec;">'
                f'<div style="font-size:12px;font-weight:600;color:#1B6B93;margin-bottom:4px;">'
                f'{icon} {label} <span style="font-weight:400;color:#999;font-size:11px;">— {note}</span></div>'
                f'<div style="font-size:12px;color:#555;line-height:1.6;">{names}</div>'
                f'</div>'
            )

        total = len(journals)
        return f"""
<details style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:0;margin-bottom:20px;">
<summary style="padding:14px 18px;cursor:pointer;font-size:14px;font-weight:600;color:#1B6B93;list-style:none;display:flex;align-items:center;gap:8px;">
  <span style="transition:transform .2s;">▶</span> 監控期刊（{total} 本）
</summary>
<div style="padding:0 18px 18px;">
  {sections}
</div>
</details>"""

    def _section_header(self, title):
        return f"""
<div style="display:flex;align-items:center;gap:10px;margin:28px 0 14px;">
  <div style="flex:1;height:1px;background:#ddd;"></div>
  <div style="font-size:12px;font-weight:600;color:#1B6B93;letter-spacing:0.5px;">{title}</div>
  <div style="flex:1;height:1px;background:#ddd;"></div>
</div>"""

    def _feedback_buttons(self, pmid: str) -> str:
        """Render feedback buttons and vote counts for an article."""
        if not self.feedback_url:
            return ""
        fb = getattr(self, "feedback_map", {}).get(pmid, {})
        total_votes = sum(fb.values())

        buttons = ""
        for rating, emoji in [("must_read", "🔥"), ("useful", "👍"), ("so_so", "➖"), ("skip", "👎")]:
            count = fb.get(rating, 0)
            count_html = f'<span class="vote-count" id="cnt-{pmid}-{rating}">{count}</span>' if count > 0 else f'<span class="vote-count" id="cnt-{pmid}-{rating}" style="display:none;">0</span>'
            buttons += (
                f'<button data-pmid="{pmid}" data-rating="{rating}" onclick="vote(\'{pmid}\',\'{rating}\',this)" '
                f'style="padding:6px 10px;border:1px solid #ddd;border-radius:6px;background:#fff;'
                f'cursor:pointer;font-size:14px;transition:all .15s;display:inline-flex;align-items:center;gap:4px;">'
                f'{emoji}{count_html}</button> '
            )

        vote_summary = ""
        if total_votes > 0:
            vote_summary = f'<span style="font-size:11px;color:#999;margin-left:4px;">{total_votes} 票</span>'

        return f"""
<div class="card-feedback" style="padding:10px 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
  {buttons}
  {vote_summary}
  <span id="voted-{pmid}" style="display:none;font-size:12px;color:#1B6B93;font-weight:600;"></span>
</div>"""

    def _upload_button(self, pmid: str, title: str, has_fulltext: bool) -> str:
        """Render PDF upload button for an article."""
        if not self.feedback_url:
            return ""
        if has_fulltext:
            return '<div style="padding:8px 0;font-size:13px;color:#085041;">✓ 已有全文分析</div>'
        safe_title = title.replace("'", "\\'").replace('"', "&quot;")
        return f"""
<div class="card-upload" style="padding:8px 0;">
  <input type="file" id="pdf-{pmid}" accept=".pdf" style="display:none"
    onchange="handlePdfSelect('{pmid}','{safe_title}',this)">
  <button id="upload-btn-{pmid}" onclick="document.getElementById('pdf-{pmid}').click()"
    style="padding:6px 14px;border:1px solid #1B6B93;border-radius:6px;background:#fff;
    color:#1B6B93;cursor:pointer;font-size:13px;transition:all .15s;">
    📄 上傳 PDF 全文分析
  </button>
  <span id="upload-status-{pmid}" style="display:none;font-size:13px;margin-left:8px;"></span>
</div>"""

    def _upload_js(self) -> str:
        """JavaScript for PDF upload and instant analysis."""
        if not self.feedback_url:
            return ""
        return f"""<script>
(function() {{
  var WEBHOOK_URL = "{self.feedback_url}";
  var SECRET = "{self.feedback_secret}";
  var DEPT = "{self.dept}";
  var uploaded = JSON.parse(localStorage.getItem('digest_uploaded') || '{{}}');

  // Restore uploaded state on load
  window.addEventListener('DOMContentLoaded', function() {{
    Object.keys(uploaded).forEach(function(pmid) {{
      var btn = document.getElementById('upload-btn-' + pmid);
      if (btn) {{
        btn.textContent = '✓ 已上傳，已分析';
        btn.disabled = true;
        btn.style.opacity = '0.5';
        btn.style.cursor = 'default';
      }}
    }});
  }});

  // JSONP helper for polling
  function jsonpGet(url, callback) {{
    var script = document.createElement('script');
    var cb = 'pdfcb_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
    window[cb] = function(resp) {{
      delete window[cb];
      document.head.removeChild(script);
      callback(resp);
    }};
    script.src = url + '&callback=' + cb;
    script.onerror = function() {{
      delete window[cb];
      document.head.removeChild(script);
      callback({{ status: 'error', message: 'Network error' }});
    }};
    document.head.appendChild(script);
  }}

  // Poll for analysis result via JSONP GET
  var POLL_TOTAL = 18;
  var POLL_STEPS = [
    '📤 PDF 已上傳，伺服器接收中...',
    '📄 正在提取 PDF 全文...',
    '📄 正在提取 PDF 全文...',
    '🔍 全文提取中，準備進行 AI 分析...',
    '🤖 Sonnet 正在深度分析全文...',
    '🤖 Sonnet 正在深度分析全文...',
    '🤖 AI 分析進行中，解讀方法學與結果...',
    '🤖 AI 分析進行中，解讀方法學與結果...',
    '🤖 AI 分析進行中，評估臨床影響...',
    '🤖 AI 分析進行中，評估臨床影響...',
    '💾 正在儲存分析結果...',
    '💾 正在儲存分析結果...',
    '⏳ 處理時間較長，請稍候...',
    '⏳ 處理時間較長，請稍候...',
    '⏳ 仍在處理中，再等一下...',
    '⏳ 仍在處理中，再等一下...',
    '⏳ 即將完成...',
    '⏳ 即將完成...'
  ];

  function pollForResult(pmid, btn, statusEl, attempts) {{
    if (attempts <= 0) {{
      btn.textContent = '❌ 分析逾時';
      btn.disabled = false;
      statusEl.textContent = '伺服器處理時間過長，請稍後再試';
      statusEl.style.color = '#E24B4A';
      return;
    }}

    // Update progress message
    var stepIdx = POLL_TOTAL - attempts;
    var elapsed = (stepIdx + 1) * 10 + 15;
    var msg = POLL_STEPS[Math.min(stepIdx, POLL_STEPS.length - 1)];
    statusEl.textContent = msg + '（' + elapsed + '秒）';

    var url = WEBHOOK_URL + '?action=check_pdf&pmid=' + pmid + '&secret=' + encodeURIComponent(SECRET) + '&dept=' + DEPT;
    jsonpGet(url, function(resp) {{
      if (resp.status === 'ok' && resp.analysis) {{
        btn.textContent = '✓ 全文分析完成';
        btn.style.color = '#085041';
        btn.style.borderColor = '#085041';
        statusEl.textContent = resp.cached ? '（已有分析結果）' : '🆕 分析完成！';
        statusEl.style.color = '#085041';
        uploaded[pmid] = true;
        localStorage.setItem('digest_uploaded', JSON.stringify(uploaded));
        renderAnalysis(pmid, resp.analysis);
      }} else if (resp.status === 'pending') {{
        setTimeout(function() {{ pollForResult(pmid, btn, statusEl, attempts - 1); }}, 10000);
      }} else {{
        btn.textContent = '❌ 分析失敗';
        btn.disabled = false;
        statusEl.textContent = resp.message || '請稍後再試';
        statusEl.style.color = '#E24B4A';
      }}
    }});
  }}

  window.handlePdfSelect = function(pmid, title, input) {{
    var file = input.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {{
      alert('PDF 檔案不能超過 10MB');
      return;
    }}

    var btn = document.getElementById('upload-btn-' + pmid);
    var statusEl = document.getElementById('upload-status-' + pmid);
    btn.textContent = '⏳ 上傳中...';
    btn.disabled = true;
    statusEl.textContent = '📤 正在上傳 PDF 至伺服器...';
    statusEl.style.display = 'inline';
    statusEl.style.color = '#1B6B93';

    var reader = new FileReader();
    reader.onload = function(e) {{
      var base64 = e.target.result.split(',')[1];

      // Step 1: Submit via hidden form + iframe (bypasses CORS entirely)
      var iframe = document.createElement('iframe');
      iframe.name = 'pdf_upload_frame_' + pmid;
      iframe.style.display = 'none';
      document.body.appendChild(iframe);

      var form = document.createElement('form');
      form.method = 'POST';
      form.action = WEBHOOK_URL;
      form.target = iframe.name;
      form.style.display = 'none';

      var fields = {{
        action: 'upload_pdf',
        pmid: pmid,
        title: title,
        pdf_base64: base64,
        secret: SECRET,
        dept: DEPT
      }};
      for (var key in fields) {{
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = key;
        input.value = fields[key];
        form.appendChild(input);
      }}

      document.body.appendChild(form);
      form.submit();

      // Clean up form after submit
      setTimeout(function() {{
        document.body.removeChild(form);
        document.body.removeChild(iframe);
      }}, 5000);

      // Step 2: Poll for result via JSONP (every 10s, up to 18 attempts = 3 min)
      setTimeout(function() {{ pollForResult(pmid, btn, statusEl, 18); }}, 15000);
    }};
    reader.readAsDataURL(file);
  }};

  window.renderAnalysis = function(pmid, data) {{
    var container = document.getElementById('analysis-result-' + pmid);
    if (!container) return;

    var a = data.deep_analysis || data;
    var html = '';

    if (a.thirty_second_summary) {{
      html += '<div class="section"><b>30 秒重點：</b>' + a.thirty_second_summary + '</div>';
    }}

    var hidden = a.hidden_findings || [];
    if (hidden.length > 0) {{
      html += '<div class="section"><div class="section-label" style="color:#712B13">Abstract 沒告訴你的事</div>';
      for (var i = 0; i < hidden.length; i++) {{
        html += '<p><b>' + (hidden[i].finding || '') + '</b> ' + (hidden[i].source || '') + '。' + (hidden[i].implication || '') + '</p>';
      }}
      html += '</div>';
    }}

    var meth = a.methodology_audit || {{}};
    var methHtml = '';
    (meth.strengths || []).forEach(function(s) {{ methHtml += '<div class="hl hl-green"><b>Strong：</b>' + s + '</div>'; }});
    (meth.notes || []).forEach(function(n) {{ methHtml += '<div class="hl hl-amber"><b>Note：</b>' + n + '</div>'; }});
    (meth.weaknesses || []).forEach(function(w) {{ methHtml += '<div class="hl hl-red"><b>Weak：</b>' + w + '</div>'; }});
    if (methHtml) {{
      html += '<div class="section"><div class="section-label" style="color:#633806">方法學評估</div>' + methHtml + '</div>';
    }}

    var impact = a.protocol_impact || {{}};
    if (impact.proposed_change) {{
      var impactHtml = '<div class="hl hl-blue">';
      if (impact.current_practice) impactHtml += '<b>目前做法：</b>' + impact.current_practice + '<br>';
      if (impact.proposed_change) impactHtml += '<b>建議調整：</b>' + impact.proposed_change + '<br>';
      if (impact.missing_evidence) impactHtml += '<b>等待的證據：</b>' + impact.missing_evidence;
      impactHtml += '</div>';
      html += '<div class="section"><div class="section-label" style="color:#085041">對我們科的具體影響</div>' + impactHtml + '</div>';
    }}

    container.innerHTML = html;
  }};
}})();
</script>"""

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

        # Feedback buttons
        feedback = self._feedback_buttons(pmid)

        # Upload PDF button
        pdf_analyses = getattr(self, "pdf_analyses", set())
        has_fulltext = bool(article.get("fulltext")) or pmid in pdf_analyses
        upload_btn = self._upload_button(pmid, article.get("title", ""), has_fulltext)

        # NEW badge for fulltext analysis
        fulltext_badge = ""
        if pmid in pdf_analyses:
            tags += '<span class="tag" style="background:#FFF3E0;color:#E65100">🆕 全文分析</span>'

        return f"""
<div class="card">
  <div class="card-tags">{tags}</div>
  <h2 class="card-title">{article.get('title', '')}</h2>
  <div class="card-authors">{article.get('authors', '')} · {article.get('pub_date', '')}</div>
  {content}
  <div id="analysis-result-{pmid}"></div>
  <div class="card-links">{links}</div>
  {feedback}
  {upload_btn}
</div>"""

    def _css(self):
        return """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Noto Sans TC',sans-serif;background:#f7f7f3;color:#333;line-height:1.8;font-size:16px}
.container{max-width:720px;margin:0 auto;padding:20px}
header{padding:20px 0;border-bottom:2px solid #1B6B93;margin-bottom:24px}
.back{font-size:15px;color:#1B6B93;text-decoration:none}
.back:hover{text-decoration:underline}
.date{font-size:15px;color:#888;margin-top:8px}
h1{font-size:26px;font-weight:700;color:#1B6B93;margin-top:4px}
.stats{font-size:15px;color:#666;margin-top:6px}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:20px;margin-bottom:18px}
.card-tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tag{padding:3px 10px;border-radius:4px;font-size:13px;font-weight:600}
.tag-journal{font-size:13px;color:#999}
.card-title{font-size:18px;font-weight:600;color:#222;line-height:1.5;margin-bottom:8px}
.card-authors{font-size:14px;color:#999;margin-bottom:14px}
.section{padding:14px 0;border-top:1px solid #f0f0ec}
.section p{font-size:15px;color:#555;margin-bottom:8px}
.section-label{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:10px}
.hl{border-left:3px solid;padding:10px 14px;margin:8px 0;font-size:15px;line-height:1.7;border-radius:0}
.hl-green{border-color:#639922;background:#EAF3DE;color:#27500A}
.hl-amber{border-color:#BA7517;background:#FAEEDA;color:#633806}
.hl-red{border-color:#E24B4A;background:#FCEBEB;color:#791F1F}
.hl-blue{border-color:#378ADD;background:#E6F1FB;color:#0C447C}
.related{font-size:15px;color:#555;padding:8px 0;border-bottom:1px solid #f5f5f0}
.related:last-child{border-bottom:none}
.card-links{padding-top:14px;display:flex;gap:16px}
.card-links a{font-size:14px;color:#1B6B93;text-decoration:none}
.card-links a:hover{text-decoration:underline}
footer{padding:24px 0;margin-top:32px;border-top:1px solid #ddd;font-size:13px;color:#999;text-align:center}
.vote-count{font-size:13px;color:#1B6B93;font-weight:600}
@media(max-width:600px){.container{padding:12px}.card{padding:16px}}
</style>"""
