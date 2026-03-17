# NICU/PICU Journal Auto-Review System

期刊文獻自動審閱與推播系統 — 馬偕紀念醫院兒科部

每日自動監控 8+ 本醫學期刊新文獻，AI 評分與摘要後推送給科內醫師。

## Features

- **每日自動抓取**: PubMed E-utilities 監控指定期刊
- **AI 分層分析**: Claude Haiku 全量評分 + Sonnet 深度分析 (Score 4-5)
- **4 維度評分**: 研究設計、臨床相關性、創新性、可推廣性
- **繁體中文輸出**: 專有名詞保留英文，其餘繁體中文
- **Email 推播**: HTML 格式日報
- **Protocol 對照**: 可載入科內工作手冊做 gap analysis
- **回饋機制**: Email URL-based feedback (Phase 2 加入 LINE)

## Quick Start

### 1. Fork this repo

### 2. Set GitHub Secrets

| Secret | Description | Required |
|--------|-------------|----------|
| `ANTHROPIC_API_KEY` | Claude API key | ✅ |
| `GMAIL_USER` | Gmail address for sending | ✅ |
| `GMAIL_APP_PASSWORD` | Gmail App Password ([generate here](https://myaccount.google.com/apppasswords)) | ✅ |
| `EMAIL_RECIPIENTS` | Comma-separated email list | ✅ |
| `NCBI_API_KEY` | PubMed API key ([get here](https://www.ncbi.nlm.nih.gov/account/settings/)) | Optional |
| `UNPAYWALL_EMAIL` | Email for Unpaywall API | Optional |
| `FEEDBACK_URL` | GitHub Pages feedback URL | Phase 2 |

### 3. Configure journals

Edit `config/journals.yaml` to add/remove journals.

### 4. Test run

Go to Actions tab → "Daily Journal Review" → "Run workflow" → check "Dry run"

### 5. Done!

System runs automatically at 07:00 Taiwan time every day.

## Adding your department's work manual

1. Place the `.docx` file in `config/manuals/`
2. Push to GitHub
3. System auto-detects and processes on next run
4. Deep analysis will reference your manual for protocol gap analysis

## Cost estimate

| Component | Monthly cost |
|-----------|-------------|
| Claude Haiku (all articles) | ~$1.5 |
| Claude Sonnet (score 4-5 only) | ~$2-3 |
| GitHub Actions | Free |
| PubMed / Unpaywall API | Free |
| **Total** | **~$3-5 USD** |

## Project structure

```
├── .github/workflows/
│   └── daily-review.yml        # Cron schedule
├── config/
│   ├── journals.yaml           # Tracked journals
│   ├── scoring_config.yaml     # Scoring weights + thresholds
│   └── manuals/                # Drop .docx work manual here
├── src/
│   ├── fetcher.py              # PubMed API client
│   ├── llm.py                  # Claude Haiku/Sonnet abstraction
│   ├── scorer.py               # Scoring + deep analysis
│   ├── fulltext.py             # Unpaywall OA lookup
│   ├── push_email.py           # Gmail SMTP sender
│   └── prompts.py              # All prompt templates
├── data/
│   ├── pmid_cache.json         # Processed PMIDs
│   ├── knowledge_base.json     # Article history
│   ├── feedback.json           # Physician feedback
│   └── on_demand_queue.json    # On-demand analysis queue
├── main.py                     # Entry point
└── requirements.txt
```

## Roadmap

- [x] Phase 1: PubMed + Haiku/Sonnet + Email
- [ ] Phase 2: LINE Bot + feedback + instant alert + on-demand
- [ ] Phase 3: Knowledge base + Zotero + weekly digest
- [ ] Phase 4: Self-evolution + personalization + guideline monitor
