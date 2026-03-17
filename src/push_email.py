"""
Email digest sender via Gmail SMTP.
Builds HTML email from scored articles and sends to department.
"""

import os
import json
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Taiwan timezone
TW_TZ = timezone(timedelta(hours=8))


class EmailPusher:
    """Send HTML digest email via Gmail SMTP."""

    def __init__(self):
        self.smtp_user = os.environ.get("GMAIL_USER", "")
        self.smtp_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
        self.recipients = os.environ.get("EMAIL_RECIPIENTS", "").split(",")
        self.recipients = [r.strip() for r in self.recipients if r.strip()]

    def send_digest(self, articles: list[dict], on_demand: list[dict] = None):
        """Build and send the daily digest email."""
        if not self.smtp_user or not self.smtp_pass:
            logger.error("Gmail credentials not configured")
            return False
        if not self.recipients:
            logger.error("No email recipients configured")
            return False

        on_demand = on_demand or []
        html = self._build_html(articles, on_demand)
        today = datetime.now(TW_TZ).strftime("%Y/%m/%d")

        # Count stats
        high_score = [a for a in articles if a.get("total_score", 0) >= 4]
        included = [a for a in articles if a.get("total_score", 0) >= 2]

        subject = f"📋 NICU/PICU Journal Digest - {today}"
        if high_score:
            must_reads = sum(1 for a in articles if a.get("total_score", 0) == 5)
            if must_reads:
                subject += f" ({must_reads} must-read)"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = ", ".join(self.recipients)

        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.smtp_user, self.recipients, msg.as_string())
            logger.info(f"Digest sent to {len(self.recipients)} recipients")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def _build_html(self, articles: list[dict], on_demand: list[dict]) -> str:
        """Build the full HTML digest."""
        today = datetime.now(TW_TZ).strftime("%Y/%m/%d (%A)")
        high = [a for a in articles if a.get("total_score", 0) >= 4]
        medium = [a for a in articles if 2 <= a.get("total_score", 0) <= 3]

        sections = []

        # On-demand from yesterday
        if on_demand:
            sections.append(self._section_header("REQUESTED BY COLLEAGUE", "#0C447C"))
            for a in on_demand:
                sections.append(self._render_deep_article(a, is_on_demand=True))

        # Score 4-5
        if high:
            sections.append(self._section_header("SCORE 4-5: DEEP ANALYSIS", "#3C3489"))
            for a in high:
                sections.append(self._render_deep_article(a))

        # Score 2-3
        if medium:
            sections.append(self._section_header("SCORE 2-3: QUICK SUMMARY", "#5F5E5A"))
            for a in medium:
                sections.append(self._render_summary_article(a))

        total = len(high) + len(medium) + len(on_demand)
        must_read = sum(1 for a in articles if a.get("total_score", 0) == 5)

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:20px;">

<!-- Header -->
<div style="padding:20px 0;border-bottom:2px solid #1B6B93;">
  <div style="font-size:13px;color:#888;">{today}</div>
  <div style="font-size:22px;font-weight:600;color:#1B6B93;margin-top:4px;">NICU/PICU Journal Digest</div>
  <div style="font-size:13px;color:#666;margin-top:8px;">
    <b>{total}</b> articles today
    {f' · <b>{must_read}</b> must-read' if must_read else ''}
    {f' · <b>{len(on_demand)}</b> colleague-requested' if on_demand else ''}
  </div>
</div>

{''.join(sections)}

<!-- Footer -->
<div style="padding:20px 0;margin-top:20px;border-top:1px solid #ddd;font-size:11px;color:#999;text-align:center;">
  NICU/PICU Journal Auto-Review System · 馬偕紀念醫院兒科部<br>
  AI scoring by Claude (Haiku + Sonnet) · Feedback shapes future scoring
</div>

</div>
</body>
</html>"""

    def _section_header(self, title: str, color: str) -> str:
        return f"""
<div style="display:flex;align-items:center;gap:10px;margin:24px 0 12px;">
  <div style="flex:1;height:1px;background:#ddd;"></div>
  <div style="font-size:11px;font-weight:600;color:{color};letter-spacing:0.5px;">{title}</div>
  <div style="flex:1;height:1px;background:#ddd;"></div>
</div>"""

    def _render_deep_article(self, article: dict, is_on_demand: bool = False) -> str:
        """Render a Score 4-5 article with deep analysis."""
        score = article.get("total_score", 0)
        deep = article.get("deep_analysis", {})
        summary = article.get("summary", {})
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")

        # Score badge color
        badge_bg = "#EEEDFE" if score == 5 else "#E1F5EE"
        badge_color = "#3C3489" if score == 5 else "#085041"

        # Tags
        tags = f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:{badge_bg};color:{badge_color};margin-right:4px;">Score {score}</span>'
        if deep:
            tags += '<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#FAECE7;color:#712B13;">Sonnet deep analysis</span>'
        if article.get("is_oa"):
            tags += ' <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#EAF3DE;color:#27500A;">OA</span>'
        if is_on_demand:
            tags += ' <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#E6F1FB;color:#0C447C;">Requested by colleague</span>'

        # Build deep analysis sections
        deep_html = ""
        if deep:
            # 30-sec summary
            thirty_sec = deep.get("thirty_second_summary", "")
            if thirty_sec:
                deep_html += f"""
<div style="padding:12px 16px;font-size:13px;color:#444;line-height:1.7;border-bottom:1px solid #eee;">
  <b>30 秒重點：</b>{thirty_sec}
</div>"""

            # Hidden findings
            hidden = deep.get("hidden_findings", [])
            if hidden:
                items = "".join(
                    f"<p style='margin:0 0 8px;'><b>{h.get('finding', '')}</b> {h.get('source', '')}。{h.get('implication', '')}</p>"
                    for h in hidden
                )
                deep_html += f"""
<div style="padding:12px 16px;border-bottom:1px solid #eee;">
  <div style="font-size:11px;font-weight:600;color:#712B13;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:8px;">Abstract 沒告訴你的事</div>
  <div style="font-size:12px;color:#555;line-height:1.7;">{items}</div>
</div>"""

            # Methodology audit
            meth = deep.get("methodology_audit", {})
            if meth:
                meth_html = ""
                for s in meth.get("strengths", []):
                    meth_html += f'<div style="border-left:3px solid #639922;background:#EAF3DE;padding:6px 10px;margin:4px 0;font-size:12px;color:#27500A;border-radius:0;line-height:1.5;"><b>Strong：</b>{s}</div>'
                for n in meth.get("notes", []):
                    meth_html += f'<div style="border-left:3px solid #BA7517;background:#FAEEDA;padding:6px 10px;margin:4px 0;font-size:12px;color:#633806;border-radius:0;line-height:1.5;"><b>Note：</b>{n}</div>'
                for w in meth.get("weaknesses", []):
                    meth_html += f'<div style="border-left:3px solid #E24B4A;background:#FCEBEB;padding:6px 10px;margin:4px 0;font-size:12px;color:#791F1F;border-radius:0;line-height:1.5;"><b>Weak：</b>{w}</div>'
                deep_html += f"""
<div style="padding:12px 16px;border-bottom:1px solid #eee;">
  <div style="font-size:11px;font-weight:600;color:#633806;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:8px;">方法學評估</div>
  {meth_html}
</div>"""

            # Protocol impact
            impact = deep.get("protocol_impact", {})
            if impact:
                current = impact.get("current_practice", "")
                proposed = impact.get("proposed_change", "")
                missing = impact.get("missing_evidence", "")
                impact_html = f"""
<div style="border-left:3px solid #378ADD;background:#E6F1FB;padding:8px 10px;margin:4px 0;font-size:12px;color:#0C447C;line-height:1.6;">
  <b>目前做法：</b>{current}<br>
  <b>建議調整：</b>{proposed}<br>
  {f'<b>等待的證據：</b>{missing}' if missing else ''}
</div>"""
                deep_html += f"""
<div style="padding:12px 16px;border-bottom:1px solid #eee;">
  <div style="font-size:11px;font-weight:600;color:#085041;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:8px;">對我們科的具體影響</div>
  {impact_html}
</div>"""
        else:
            # Fallback: Haiku summary only
            s = summary
            deep_html = f"""
<div style="padding:12px 16px;font-size:13px;color:#444;line-height:1.7;">
  <p style="margin:0 0 6px;"><b>研究目的：</b>{s.get('purpose', '')}</p>
  <p style="margin:0 0 6px;"><b>研究設計：</b>{s.get('design', '')}</p>
  <p style="margin:0 0 6px;"><b>主要發現：</b>{s.get('findings', '')}</p>
  <p style="margin:0;"><b>臨床意義：</b>{s.get('significance', '')}</p>
</div>"""

        # Links
        links = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" style="color:#1B6B93;text-decoration:none;font-size:12px;">PubMed →</a>'
        if doi:
            links += f' &nbsp; <a href="https://doi.org/{doi}" style="color:#1B6B93;text-decoration:none;font-size:12px;">DOI →</a>'
        if article.get("oa_url"):
            links += f' &nbsp; <a href="{article["oa_url"]}" style="color:#1B6B93;text-decoration:none;font-size:12px;">Full text (OA) →</a>'

        # Feedback buttons (URL-based for email)
        feedback_base = os.environ.get("FEEDBACK_URL", "")
        feedback_html = ""
        if feedback_base:
            ratings = [
                ("Must read", "#EEEDFE", "#3C3489"),
                ("Useful", "#E1F5EE", "#085041"),
                ("So-so", "#F1EFE8", "#5F5E5A"),
                ("Not relevant", "#FCEBEB", "#791F1F"),
            ]
            btns = ""
            for label, bg, color in ratings:
                url = f"{feedback_base}?pmid={pmid}&rating={label.lower().replace(' ', '_')}"
                btns += f'<a href="{url}" style="flex:1;text-align:center;padding:8px;background:{bg};color:{color};text-decoration:none;font-size:11px;font-weight:600;border-radius:6px;">{label}</a>'
            feedback_html = f'<div style="display:flex;gap:6px;padding:0 16px 14px;">{btns}</div>'

        return f"""
<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;margin-bottom:16px;overflow:hidden;">
  <div style="padding:14px 16px;">{tags}</div>
  <div style="padding:0 16px;font-size:15px;font-weight:600;color:#222;line-height:1.4;">{article['title']}</div>
  <div style="padding:4px 16px 0;font-size:11px;color:#999;">{article['authors']} · {article.get('source_journal', '')} · {article.get('pub_date', '')}</div>
  {deep_html}
  <div style="padding:10px 16px;">{links}</div>
  {feedback_html}
</div>"""

    def _render_summary_article(self, article: dict) -> str:
        """Render a Score 2-3 article with Haiku summary."""
        score = article.get("total_score", 0)
        summary = article.get("summary", {})
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")

        # Feedback URL
        feedback_base = os.environ.get("FEEDBACK_URL", "")
        deep_btn = ""
        if feedback_base:
            deep_url = f"{feedback_base}?pmid={pmid}&action=deep_analysis"
            deep_btn = f' &nbsp; <a href="{deep_url}" style="color:#3C3489;text-decoration:none;font-size:12px;font-weight:600;">Deep analysis →</a>'

        links = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" style="color:#1B6B93;text-decoration:none;font-size:12px;">PubMed →</a>'
        if doi:
            links += f' &nbsp; <a href="https://doi.org/{doi}" style="color:#1B6B93;text-decoration:none;font-size:12px;">DOI →</a>'

        # Feedback buttons
        feedback_html = ""
        if feedback_base:
            ratings = [
                ("Must read", "#EEEDFE", "#3C3489"),
                ("Useful", "#E1F5EE", "#085041"),
                ("So-so", "#F1EFE8", "#5F5E5A"),
                ("Not relevant", "#FCEBEB", "#791F1F"),
            ]
            btns = ""
            for label, bg, color in ratings:
                url = f"{feedback_base}?pmid={pmid}&rating={label.lower().replace(' ', '_')}"
                btns += f'<a href="{url}" style="flex:1;text-align:center;padding:7px;background:{bg};color:{color};text-decoration:none;font-size:11px;font-weight:600;border-radius:6px;">{label}</a>'
            feedback_html = f'<div style="display:flex;gap:6px;padding:0 16px 12px;">{btns}</div>'

        return f"""
<div style="background:#fff;border:1px solid #e8e8e4;border-radius:12px;margin-bottom:12px;overflow:hidden;">
  <div style="padding:12px 16px;">
    <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#F1EFE8;color:#5F5E5A;">Score {score}</span>
    <span style="font-size:11px;color:#999;margin-left:6px;">{article.get('source_journal', '')} · {article.get('pub_date', '')}</span>
  </div>
  <div style="padding:0 16px;font-size:14px;font-weight:600;color:#333;line-height:1.4;">{article['title']}</div>
  <div style="padding:4px 16px 0;font-size:11px;color:#999;">{article['authors']}</div>
  <div style="padding:12px 16px;font-size:13px;color:#555;line-height:1.7;">
    <p style="margin:0 0 6px;"><b>研究目的：</b>{summary.get('purpose', '')}</p>
    <p style="margin:0 0 6px;"><b>研究設計：</b>{summary.get('design', '')}</p>
    <p style="margin:0 0 6px;"><b>主要發現：</b>{summary.get('findings', '')}</p>
    <p style="margin:0;"><b>臨床意義：</b>{summary.get('significance', '')}</p>
  </div>
  <div style="padding:8px 16px;">{links}{deep_btn}</div>
  {feedback_html}
</div>"""
