#!/usr/bin/env python3
"""Generate root index.html that links to all department digest sites."""

from pathlib import Path

DEPARTMENTS = [
    {
        "id": "newborn",
        "name": "新生兒科",
        "name_en": "NICU / Neonatology",
        "icon": "👶",
        "color": "#1B6B93",
    },
    {
        "id": "cardiology",
        "name": "小兒心臟科",
        "name_en": "Pediatric Cardiology",
        "icon": "❤️",
        "color": "#C0392B",
    },
]


def main():
    cards = ""
    for dept in DEPARTMENTS:
        cards += f"""
<a href="{dept['id']}/index.html" class="dept-card" style="border-color:{dept['color']};">
  <div class="dept-icon">{dept['icon']}</div>
  <div class="dept-name" style="color:{dept['color']};">{dept['name']}</div>
  <div class="dept-name-en">{dept['name_en']}</div>
</a>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Journal Digest - 馬偕紀念醫院</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Noto Sans TC',sans-serif;background:#f7f7f3;color:#333;min-height:100vh;display:flex;justify-content:center;align-items:center}}
.container{{max-width:480px;width:90%;padding:40px 0;text-align:center}}
h1{{font-size:24px;font-weight:700;color:#333;margin-bottom:6px}}
.subtitle{{font-size:14px;color:#888;margin-bottom:32px}}
.dept-card{{display:block;padding:24px;border:2px solid #e0e0e0;border-radius:16px;margin-bottom:16px;text-decoration:none;color:inherit;transition:all .2s;background:#fff}}
.dept-card:hover{{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,0.1)}}
.dept-icon{{font-size:32px;margin-bottom:8px}}
.dept-name{{font-size:18px;font-weight:600;margin-bottom:4px}}
.dept-name-en{{font-size:13px;color:#999}}
footer{{margin-top:32px;font-size:12px;color:#bbb}}
</style>
</head>
<body>
<div class="container">
  <h1>Journal Digest</h1>
  <div class="subtitle">馬偕紀念醫院 · AI-powered daily literature review</div>
  {cards}
  <footer>AI scoring by Claude (Haiku + Sonnet)</footer>
</div>
</body>
</html>"""

    output = Path("docs/index.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Root index generated: {output}")


if __name__ == "__main__":
    main()
