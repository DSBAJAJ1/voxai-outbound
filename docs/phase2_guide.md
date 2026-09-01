# Phase 2 & 3 Setup Guide

This guide covers everything needed to upgrade from Phase 1 (single city, GMaps only)
to the full 100-lead/day pipeline with Meta Ads, enrichment, international regions,
and follow-up automation.

> [!IMPORTANT]
> **Only start Phase 2 after Phase 1 has produced real sends and at least some replies.**
> The spec is explicit: do not scale until the core loop is validated.

---

## Step 1 — Run Phase 2 Supabase Functions

In Supabase → **SQL Editor → New Query**, paste and run `supabase/functions.sql`.

This adds:
- `pg_trgm` extension (fuzzy matching)
- `find_fuzzy_name_match()` function
- `check_lead_duplicate()` function — called by the Phase 2 n8n workflow

**Test it works:**
```sql
SELECT check_lead_duplicate('+919876543210', 'Test Coaching Centre', 'IN');
-- Expected: {"is_duplicate": false} (assuming no such lead exists yet)
```

---

## Step 2 — Create Serper.dev Account

1. Go to [serper.dev](https://serper.dev) → **Sign Up** (free)
2. You get **2,500 free credits** on signup — enough for ~25 days of Phase 2 at 100/day
3. After free credits: **$50 for 50,000 credits** (lasts ~6 months) — about $8/month
4. Copy your API key from Dashboard → **API Key**
5. Add to your Railway n8n service → **Variables**:
   ```
   SERPER_API_KEY = your-key-here
   ```

---

## Step 3 — Create Apify Account

1. Go to [apify.com](https://apify.com) → **Sign Up**
2. Free tier gives $5/month of compute credit — enough for testing
3. In Apify Dashboard → **Settings → Integrations → API Tokens** → **Create token**
4. Copy the token and add to Railway n8n → **Variables**:
   ```
   APIFY_API_TOKEN = your-token-here
   ```

### Test the Apify actor manually
In Apify console → **Actors** → search `facebook-ads-scraper` → **apify/facebook-ads-scraper** → **Try for free**:
- Input: `{ "countryCode": "IN", "searchTerms": ["coaching institutes"], "maxItems": 5 }`
- Run it → verify you get ads with `pageName`, `body_text`, `link_url`

---

## Step 4 — Deploy Updated Scraper to Railway

The scraper now has a new `/enrich/website` endpoint (added in Phase 2).
Push the updated code and Railway will auto-redeploy:

```bash
cd /path/to/voxai-outbound
git add scraper/
git commit -m "Phase 2: add website enricher endpoint"
git push
```

**Verify after deploy:**
```bash
curl -X POST https://YOUR-SCRAPER-URL.up.railway.app/enrich/website \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.example.com"}'
```
Expected: `{ "fetch_success": true, "title": "...", "has_chat_widget": false, ... }`

---

## Step 5 — Add Residential Proxy (Required for Full Volume)

Without a proxy, Google Maps silently strips phone numbers. At 50 queries/day
(GMaps India + International), you will hit bot detection without a proxy.

**Recommended options:**
| Provider | Price | Best for |
|---|---|---|
| [Smartproxy](https://smartproxy.com) | ~$12.5/GB | Best value, good India coverage |
| [Bright Data](https://brightdata.com) | ~$15/GB | Most reliable, largest pool |
| [Oxylabs](https://oxylabs.io) | ~$15/GB | Good global coverage |

After getting a proxy:
1. Get a proxy URL in format: `http://username:password@proxy-host:port`
2. Add to Railway scraper service → **Variables**:
   ```
   PROXY_URL = http://user:pass@gate.smartproxy.com:7000
   ```
3. Verify: `GET /health` should now return `"proxy_configured": true`

---

## Step 6 — Import Phase 2 Workflow into n8n

1. In n8n → **Workflows → Import from File**
2. Upload `n8n/phase2_full_pipeline.json`
3. Open each **Postgres node** → confirm it uses the **Supabase Postgres** credential
4. The workflow will run all 4 sources in parallel:
   - GMaps India (30) + International (20) via batch endpoint
   - Apify Meta Ads India (30) + International (20)

### First manual run
Click **Test Workflow** to run once. Monitor:
- GMaps batch nodes: should return `total_leads > 0`
- Apify run IDs: logged in `apify-meta-india-start.json.data.id`
- Dedupe check: `is_duplicate: false` for new leads
- Claude outputs: `pain_point` and `whatsapp_draft` populated
- Supabase: `SELECT COUNT(*) FROM leads WHERE status = 'pending_approval';`

---

## Step 7 — Phase 3: Follow-up Automation + Hot Lead Alerts

### Import the Phase 3 workflow
1. n8n → **Import** → `n8n/phase3_followup.json`
2. This is a **separate workflow** running at 9:30 AM IST daily (independent cron)

### Set up Telegram bot for hot-lead alerts

1. Message [@BotFather](https://t.me/botfather) on Telegram → `/newbot` → get bot token
2. Start a chat with your new bot, then get your chat ID:
   ```
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Find `"chat": {"id": YOUR_CHAT_ID}` in the response
3. In n8n → **Credentials → Telegram Bot** → add your bot token
4. Add to Railway n8n Variables:
   ```
   TELEGRAM_CHAT_ID = your-chat-id
   ```

### Mark leads as replied / hot_lead (manual for Phase 3)
When someone replies positively to your WhatsApp outreach:
```sql
-- Mark as replied
UPDATE leads SET status = 'replied', replied_at = NOW() WHERE id = 'lead-uuid-here';

-- Mark as hot lead (triggers Telegram alert on next cron run)
UPDATE leads SET status = 'hot_lead' WHERE id = 'lead-uuid-here';
```

The Phase 3 workflow checks for `hot_lead` leads updated in the last hour and fires the alert.

---

## Daily Workflow Summary (Full Phase 2 Running)

| Time (IST) | What Happens |
|---|---|
| 2:00 AM | Phase 2 pipeline runs: scrape → enrich → AI draft → queue |
| 6:30–8:00 AM | International leads ready for approval (Gulf/Singapore timezone) |
| 8:00–9:30 AM | Review + approve international leads → send via WhatsApp |
| 9:30 AM | Phase 3 follow-up check runs; hot lead alerts fire |
| 10:00 AM–1:00 PM | India leads ready → approve + send |
| Ongoing | Mark replies → `replied` status → positive ones → `hot_lead` |

---

## Environment Variables — Full List

Add all of these to your Railway n8n service **Variables**:

| Variable | Source |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free, no credit card |
| `SCRAPER_BASE_URL` | Railway scraper service public URL |
| `SERPER_API_KEY` | [serper.dev](https://serper.dev) dashboard |
| `APIFY_API_TOKEN` | Apify → Settings → API Tokens |
| `TELEGRAM_CHAT_ID` | Telegram `/getUpdates` API call |

Add these to your Railway **scraper** service **Variables**:

| Variable | Value |
|---|---|
| `HEADLESS` | `true` |
| `PROXY_URL` | `http://user:pass@proxy-host:port` (add when proxy ready) |
