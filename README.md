# VoxAI Outbound Lead Generation System

A semi-automated outbound prospecting pipeline for **VoxAI Agents**.
Scrapes leads daily from Google Maps and Meta Ads Library, enriches them with AI-generated pain-point analysis and personalized outreach messages, and queues them for human approval before sending.

*Last updated: 2026-09-02*

## Architecture

```
Google Maps Scraper (Python/Playwright)
        │
        ▼
Dedupe Check (Supabase)
        │
        ▼
AI Pain-Point Detection (Claude Sonnet 5)
        │
        ▼
AI Message Drafting (Claude Sonnet 5)
        │
        ▼
Approval Queue (Supabase View)  ← Human reviews here
        │
        ▼
Manual Send (WhatsApp Business App via wa.me deep links)
        │
        ▼
CRM Tracking (Supabase — status, sent_at, replied_at)
```

## Tech Stack

| Layer | Tool |
|---|---|
| Orchestration | n8n (Railway-hosted) |
| Google Maps Scraping | Python FastAPI + Playwright + playwright-stealth (Railway) |
| Meta Ads Scraping | Apify `apify/facebook-ads-scraper` (Phase 2) |
| Decision-maker Lookup | Serper.dev Google X-ray search (Phase 2) |
| AI | Claude Sonnet 5 via Anthropic API |
| Database | Supabase (Postgres) |
| Delivery | Manual — WhatsApp Business App + `wa.me` deep links |

## Directory Structure

```
voxai-outbound/
├── scraper/                # Python FastAPI scraper + enricher service
│   ├── main.py             # FastAPI endpoints (/scrape/gmaps, /enrich/website, etc.)
│   ├── gmaps_scraper.py    # Playwright scraping logic
│   ├── website_enricher.py # Website fetch + chat widget detection (Phase 2)
│   ├── phone_normalizer.py # E.164 phone normalization
│   ├── query_rotator.py    # Daily query rotation
│   ├── queries.json        # Niche × city rotation list (30 India + 20 Intl)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── railway.toml
├── n8n/
│   ├── phase1_pipeline.json     # Phase 1: GMaps India (1 city) → Supabase → AI
│   ├── phase2_full_pipeline.json # Phase 2: All 4 sources + enrichment + intl
│   └── phase3_followup.json      # Phase 3: Follow-ups + Telegram hot-lead alerts
├── supabase/
│   ├── schema.sql          # Run first: tables, views, indexes
│   └── functions.sql       # Run second: fuzzy dedupe functions (Phase 2)
├── prompts/
│   ├── pain_point_detection.txt  # Layer 4 AI prompt
│   └── message_drafting.txt      # Layer 5 prompts (WA, LinkedIn, follow-up)
└── docs/
    ├── setup_guide.md      # Phase 1 step-by-step setup
    └── phase2_guide.md     # Phase 2 & 3 setup (Serper, Apify, proxy, Telegram)
```

## Quick Start

→ See **[docs/setup_guide.md](docs/setup_guide.md)** for full step-by-step instructions.

**TL;DR:**
1. Run `supabase/schema.sql` in Supabase SQL Editor
2. Deploy `scraper/` to Railway (auto-detects Dockerfile)
3. Import `n8n/phase1_pipeline.json` into your Railway n8n
4. Add environment variables: `ANTHROPIC_API_KEY`, `SCRAPER_BASE_URL`
5. Test manually → approve leads from the `approval_queue` view → send

## Build Phases

| Phase | Status | Scope |
|---|---|---|
| Phase 1 | ✅ Built | GMaps scraper (1 India city) → Supabase → Claude AI drafts |
| Phase 2 | ✅ Built | Full 100/day volume, Meta Ads, website enrichment, international |
| Phase 3 | ✅ Built | Follow-up automation, Telegram hot-lead alerts |

## Important Constraints

- **No automated sending**: WhatsApp and LinkedIn outbound is intentionally manual.
  The `wa.me` deep links pre-fill messages but a human clicks Send every time.
- **Proxy required at scale**: Google Maps silently strips phone numbers for detected bots.
  Set `PROXY_URL` env var on the Railway scraper service before running at full volume.
- **Human approval required**: Every AI-drafted message goes through the `approval_queue`
  before any send action. This is for both message quality and platform safety.
