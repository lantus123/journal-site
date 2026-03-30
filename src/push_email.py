"""
Email digest sender via Resend API.
Builds HTML email from scored articles and sends to department.
"""

import hashlib
import os
import logging
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))

RESEND_API_URL = "https://api.resend.com/emails"


class EmailPusher:
    """Send HTML digest email via Resend."""

    def __init__(self, dept_label: str = "新生兒科 NB", dept_short: str = "NB"):
        self.api_key = os.environ.get("RESEND_API_KEY", "")
        self.from_address = os.environ.get(
            "EMAIL_FROM", "NICU Journal Bot <nicu-journal@schedule.mmhped.org>"
        )
        self.recipients = os.environ.get("EMAIL_RECIPIENTS", "").split(",")
        self.recipients = [r.strip() for r in self.recipients if r.strip()]
        self.feedback_url = os.environ.get("FEEDBACK_WEBHOOK_URL", "")
        self.feedback_secret = os.environ.get("FEEDBACK_SECRET", "")
        self.dept_label = dept_label
        self.dept_short = dept_short

    def send_digest(self, articles: list[dict], on_demand: list[dict] = None, total_scanned: int = 0):
        """Build and send the daily digest email."""
        if not self.api_key:
            logger.error("Resend API key not configured")
            return False
        if not self.recipients:
            logger.error("No email recipients configured")
            return False

        on_demand = on_demand or []
        today = datetime.now(TW_TZ).strftime("%Y/%m/%d")

        # Empty digest: send brief notification instead of full email
        if not articles and not on_demand:
            subject = f"{self.dept_short} Journal Digest - {today} (no articles qualified)"
            html = self._build_empty_html(today, total_scanned)
            return self._send_to_all(subject, html)

        must_reads = sum(1 for a in articles if a.get("total_score", 0) == 5)

        subject = f"{self.dept_short} Journal Digest - {today}"
        if must_reads:
            subject += f" ({must_reads} must-read)"

        # Send per-recipient for unique feedback uid
        success = True
        for recipient in self.recipients:
            html = self._build_html(articles, on_demand, recipient)
            try:
                resp = requests.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": self.from_address,
                        "to": [recipient],
                        "subject": subject,
                        "html": html,
                    },
                    timeout=30,
                )

                if resp.status_code == 200:
                    logger.info(f"Digest sent to {recipient} via Resend")
                else:
                    logger.error(f"Resend failed for {recipient}: {resp.status_code} {resp.text}")
                    success = False

            except Exception as e:
                logger.error(f"Failed to send email to {recipient}: {e}")
                success = False

        return success

    def _send_to_all(self, subject: str, html: str) -> bool:
        """Send the same HTML to all recipients."""
        success = True
        for recipient in self.recipients:
            try:
                resp = requests.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": self.from_address,
                        "to": [recipient],
                        "subject": subject,
                        "html": html,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    logger.info(f"Email sent to {recipient}")
                else:
                    logger.error(f"Resend failed for {recipient}: {resp.status_code} {resp.text}")
                    success = False
            except Exception as e:
                logger.error(f"Failed to send email to {recipient}: {e}")
                success = False
        return success

    def _build_empty_html(self, today: str, total_scanned: int) -> str:
        """Build a minimal HTML email for days with no qualifying articles."""
        scanned_msg = f"已掃描 <b>{total_scanned}</b> 篇文章" if total_scanned else "今日無新文章"
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:20px;">
<div style="padding:20px 0;border-bottom:2px solid #1B6B93;">
  <div style="font-size:13px;color:#888;">{today}</div>
  <div style="font-size:22px;font-weight:600;color:#1B6B93;margin-top:4px;">{self.dept_short} Journal Digest</div>
</div>
<div style="padding:30px 0;text-align:center;color:#666;">
  <div style="font-size:16px;">{scanned_msg}</div>
  <div style="font-size:14px;margin-top:8px;color:#999;">無文章達到推薦門檻（score &ge; 2）</div>
</div>
<div style="padding:20px 0;margin-top:20px;border-top:1px solid #ddd;font-size:11px;color:#999;text-align:center;">
  {self.dept_label} Journal Auto-Review System · 馬偕紀念醫院<br>
  AI scoring by Claude (Haiku + Sonnet)
</div>
</div>
</body>
</html>"""

    def _build_html(self, articles: list[dict], on_demand: list[dict], recipient: str = "") -> str:
        """Build the full HTML digest."""
        today = datetime.now(TW_TZ).strftime("%Y/%m/%d (%A)")
        high = [a for a in articles if a.get("total_score", 0) >= 4]
        medium = [a for a in articles if 2 <= a.get("total_score", 0) <= 3]

        sections = []

        if on_demand:
            sections.append(self._section_header("REQUESTED BY COLLEAGUE", "#0C447C"))
            for a in on_demand:
                sections.append(self._render_deep_article(a, is_on_demand=True, recipient=recipient))

        if high:
            sections.append(self._section_header("SCORE 4-5: DEEP ANALYSIS", "#3C3489"))
            for a in high:
                sections.append(self._render_deep_article(a, recipient=recipient))

        if medium:
            sections.append(self._section_header("SCORE 2-3: QUICK SUMMARY", "#5F5E5A"))
            for a in medium:
                sections.append(self._render_summary_article(a, recipient=recipient))

        total = len(high) + len(medium) + len(on_demand)
        must_read = sum(1 for a in articles if a.get("total_score", 0) == 5)

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:20px;">

<div style="padding:20px 0;border-bottom:2px solid #1B6B93;">
  <div style="font-size:13px;color:#888;">{today}</div>
  <div style="font-size:22px;font-weight:600;color:#1B6B93;margin-top:4px;">{self.dept_short} Journal Digest</div>
  <div style="font-size:13px;color:#666;margin-top:8px;">
    <b>{total}</b> articles today
    {f' · <b>{must_read}</b> must-read' if must_read else ''}
    {f' · <b>{len(on_demand)}</b> colleague-requested' if on_demand else ''}
  </div>
</div>

{''.join(sections)}

<div style="padding:20px 0;margin-top:20px;border-top:1px solid #ddd;font-size:11px;color:#999;text-align:center;">
  {self.dept_label} Journal Auto-Review System · 馬偕紀念醫院<br>
  AI scoring by Claude (Haiku + Sonnet) · Feedback shapes future scoring
</div>

</div>
</body>
</html>"""

    def _feedback_buttons(self, pmid: str, recipient: str) -> str:
        """Render email feedback buttons for an article."""
        if not self.feedback_url:
            return ""
        uid = "email_" + hashlib.sha256(recipient.encode()).hexdigest()[:8]
        buttons = ""
        for rating, emoji, label in [
            ("must_read", "🔥", "Must read"),
            ("useful", "👍", "Useful"),
            ("so_so", "➖", "So-so"),
            ("skip", "👎", "Skip"),
        ]:
            url = (
                f"{self.feedback_url}?action=feedback&pmid={pmid}"
                f"&rating={rating}&uid={uid}&source=email&secret={self.feedback_secret}"
            )
            buttons += (
                f'<a href="{url}" style="display:inline-block;padding:4px 12px;'
                f'border:1px solid #ddd;border-radius:6px;text-decoration:none;'
                f'font-size:12px;color:#555;margin-right:4px;">'
                f'{emoji} {label}</a>'
            )
        return f'<div style="padding:8px 16px 4px;">{buttons}</div>'

    def _section_header(self, title: str, color: str) -> str:
        return f"""
<div style="display:flex;align-items:center;gap:10px;margin:24px 0 12px;">
  <div style="flex:1;height:1px;background:#ddd;"></div>
  <div style="font-size:11px;font-weight:600;color:{color};letter-spacing:0.5px;">{title}</div>
  <div style="flex:1;height:1px;background:#ddd;"></div>
</div>"""

    def _render_deep_article(self, article: dict, is_on_demand: bool = False, recipient: str = "") -> str:
        score = article.get("total_score", 0)
        deep = article.get("deep_analysis", {})
        summary = article.get("summary", {})
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")

        badge_bg = "#EEEDFE" if score == 5 else "#E1F5EE"
        badge_color = "#3C3489" if score == 5 else "#085041"

        tags = f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:{badge_bg};color:{badge_color};margin-right:4px;">Score {score}</span>'
        if deep:
            tags += '<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#FAECE7;color:#712B13;">Sonnet deep analysis</span>'
        if article.get("is_oa"):
            tags += ' <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#EAF3DE;color:#27500A;">OA</span>'
        if is_on_demand:
            tags += ' <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#E6F1FB;color:#0C447C;">Requested by colleague</span>'

        deep_html = ""
        if deep:
            thirty_sec = deep.get("thirty_second_summary", "")
            if thirty_sec:
                deep_html += f"""
<div style="padding:12px 16px;font-size:13px;color:#444;line-height:1.7;border-bottom:1px solid #eee;">
  <b>30 秒重點：</b>{thirty_sec}
</div>"""

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

            meth = deep.get("methodology_audit", {})
            if meth:
                meth_html = ""
                for s in meth.get("strengths", []):
                    meth_html += f'<div style="border-left:3px solid #639922;background:#EAF3DE;padding:6px 10px;margin:4px 0;font-size:12px;color:#27500A;line-height:1.5;"><b>Strong：</b>{s}</div>'
                for n in meth.get("notes", []):
                    meth_html += f'<div style="border-left:3px solid #BA7517;background:#FAEEDA;padding:6px 10px;margin:4px 0;font-size:12px;color:#633806;line-height:1.5;"><b>Note：</b>{n}</div>'
                for w in meth.get("weaknesses", []):
                    meth_html += f'<div style="border-left:3px solid #E24B4A;background:#FCEBEB;padding:6px 10px;margin:4px 0;font-size:12px;color:#791F1F;line-height:1.5;"><b>Weak：</b>{w}</div>'
                if meth_html:
                    deep_html += f"""
<div style="padding:12px 16px;border-bottom:1px solid #eee;">
  <div style="font-size:11px;font-weight:600;color:#633806;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:8px;">方法學評估</div>
  {meth_html}
</div>"""

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
            s = summary
            deep_html = f"""
<div style="padding:12px 16px;font-size:13px;color:#444;line-height:1.7;">
  <p style="margin:0 0 6px;"><b>研究目的：</b>{s.get('purpose', '')}</p>
  <p style="margin:0 0 6px;"><b>研究設計：</b>{s.get('design', '')}</p>
  <p style="margin:0 0 6px;"><b>主要發現：</b>{s.get('findings', '')}</p>
  <p style="margin:0;"><b>臨床意義：</b>{s.get('significance', '')}</p>
</div>"""

        links = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" style="color:#1B6B93;text-decoration:none;font-size:12px;">PubMed →</a>'
        if doi:
            links += f' &nbsp; <a href="https://doi.org/{doi}" style="color:#1B6B93;text-decoration:none;font-size:12px;">DOI →</a>'
        if article.get("oa_url"):
            links += f' &nbsp; <a href="{article["oa_url"]}" style="color:#1B6B93;text-decoration:none;font-size:12px;">Full text (OA) →</a>'

        return f"""
<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;margin-bottom:16px;overflow:hidden;">
  <div style="padding:14px 16px;">{tags}</div>
  <div style="padding:0 16px;font-size:15px;font-weight:600;color:#222;line-height:1.4;">{article['title']}</div>
  <div style="padding:4px 16px 0;font-size:11px;color:#999;">{article['authors']} · {article.get('source_journal', '')} · {article.get('pub_date', '')}</div>
  {deep_html}
  {self._feedback_buttons(pmid, recipient)}
  <div style="padding:10px 16px 14px;">{links}</div>
</div>"""

    def _render_summary_article(self, article: dict, recipient: str = "") -> str:
        score = article.get("total_score", 0)
        summary = article.get("summary", {})
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")

        links = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" style="color:#1B6B93;text-decoration:none;font-size:12px;">PubMed →</a>'
        if doi:
            links += f' &nbsp; <a href="https://doi.org/{doi}" style="color:#1B6B93;text-decoration:none;font-size:12px;">DOI →</a>'

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
    <p style="margin:0 0 6px;"><b>主要發現：</b>{summary.get('findings', '')}</p>
    <p style="margin:0;"><b>臨床意義：</b>{summary.get('significance', '')}</p>
  </div>
  {self._feedback_buttons(pmid, recipient)}
  <div style="padding:8px 16px 14px;">{links}</div>
</div>"""
