# VoxAI Outbound — Setup Guide (Phase 1)

Follow these steps in order. Phase 1 gets you from zero to your first batch of
AI-drafted WhatsApp messages ready for manual approval and sending.

Estimated time: **2–3 hours for initial setup**, then 10 minutes/day for approval + sending.

---

## Step 1 — Supabase Database

### 1.1 Create a free Supabase project
1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Choose a name: `voxai-outbound`
3. Set a strong DB password (save it — you'll need it for n8n)
4. Region: **South Asia (Mumbai)** for lowest latency from India

### 1.2 Run the schema
1. In Supabase Dashboard → **SQL Editor** → **New Query**
2. Paste the entire contents of `supabase/schema.sql`
3. Click **Run** — you should see success messages for all tables, indexes, and views

### 1.3 Get connection details
From Supabase: **Settings → Database → Connection string**
- Copy the **Direct connection** URI — it looks like:
  `postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres`
- Save this for n8n credentials

---

## Step 2 — Groq API Key (Free — no credit card needed)

Groq provides **free** access to Llama 3.3 70B — the model used for all AI steps
in this pipeline. The free tier gives **14,400 API calls/day**, which is more than
enough for 100 leads × 2–3 calls each.

1. Go to [console.groq.com](https://console.groq.com) → **Sign Up** (Google/GitHub login)
2. **API Keys → Create API Key** → name it `voxai-n8n`
3. Copy the key (starts with `gsk_...`)
4. Add to Railway n8n service → **Variables**:
   ```
   GROQ_API_KEY = gsk_...
   ```

**Cost:** Completely free. No billing required.

> [!TIP]
> If you ever want **higher quality outputs** for the AI drafting step, you can
> optionally switch to Claude by creating an account at [console.anthropic.com](https://console.anthropic.com),
> setting `ANTHROPIC_API_KEY`, and updating the n8n HTTP Request node URLs back to
> `https://api.anthropic.com/v1/messages` with the Anthropic header format.
> Groq is the default — it’s free and fast.

---

## Step 3 — Serper.dev (Phase 2 — skip for Phase 1)

> You don't need Serper.dev for Phase 1. Set this up before starting Phase 2.

1. Go to [serper.dev](https://serper.dev) → **Sign Up** (free, no credit card)
2. You get **2,500 free credits** on signup — enough to test Phase 2 enrichment
3. Copy your API key from the dashboard

---

## Step 4 — Apify (Phase 2 — skip for Phase 1)

> You don't need Apify for Phase 1. Set this up before starting Phase 2.

1. Go to [apify.com](https://apify.com) → **Sign Up** (free tier: $5/month credit)
2. From the Dashboard → **Settings → Integrations → API Tokens** → Create token
3. Copy the token
4. In Apify Store, search for **"Facebook Ads Library Scraper"** → use actor `apify/facebook-ads-scraper`

---

## Step 5 — Deploy the Scraper to Railway

### 5.1 Push the scraper code to GitHub
```bash
cd /path/to/voxai-outbound
git init
git add scraper/
git commit -m "Phase 1: GMaps scraper FastAPI"
git remote add origin https://github.com/YOUR_USERNAME/voxai-outbound.git
git push -u origin main
```

### 5.2 Create a Railway service
1. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. Select your `voxai-outbound` repository
3. Railway will detect the Dockerfile automatically (it's in the `scraper/` directory)
4. If Railway doesn't detect it: **Settings → Build → Dockerfile Path** → set to `scraper/Dockerfile`

### 5.3 Set environment variables on Railway
In your Railway service → **Variables**, add:

| Variable | Value |
|---|---|
| `PORT` | `8000` (Railway sets this automatically) |
| `HEADLESS` | `true` |
| `PROXY_URL` | *(leave empty for now — add when you get a residential proxy)* |

### 5.4 Get your scraper URL
After deploy: Railway → your service → **Settings → Networking → Public URL**
It'll look like: `https://voxai-gmaps-scraper-production.up.railway.app`

### 5.5 Test the scraper
```bash
curl https://YOUR-RAILWAY-URL.up.railway.app/health
```
Expected: `{"status":"ok","service":"voxai-gmaps-scraper","proxy_configured":false}`

---

## Step 6 — Configure n8n on Railway

### 6.1 Add credentials in n8n
In your Railway n8n instance → **Settings → Credentials**:

**Supabase Postgres credential:**
- Type: **Postgres**
- Host: `db.[PROJECT-REF].supabase.co`
- Port: `5432`
- Database: `postgres`
- User: `postgres`
- Password: your Supabase DB password
- SSL: **Required**

### 6.2 Add environment variables to n8n on Railway
In your n8n Railway service → **Variables**:

| Variable | Value |
|---|---|
| `GROQ_API_KEY` | `gsk_...` (from console.groq.com) |
| `SCRAPER_BASE_URL` | `https://YOUR-RAILWAY-SCRAPER-URL.up.railway.app` |

### 6.3 Import the Phase 1 workflow
1. In n8n: **Workflows → Import from File**
2. Upload `n8n/phase1_pipeline.json`
3. The workflow will import with all nodes pre-configured

### 6.4 Verify credentials are linked
After importing, open each Postgres node and confirm it uses the **Supabase Postgres** credential you created in Step 6.1.

---

## Step 7 — First Manual Test Run

**Before activating the daily cron, test manually:**

1. In n8n, open the Phase 1 workflow
2. Click **Test Workflow** (runs once immediately)
3. Watch each node execute — green = success, red = error
4. After completion, check Supabase:
   - `SELECT * FROM leads LIMIT 5;` — should show leads with `status = 'pending_approval'`
   - `SELECT * FROM approval_queue;` — your approval view

### What to look for
- ✅ `business_name` is populated
- ✅ `phone_normalized` is in E.164 format (e.g. `+919876543210`)
- ✅ `pain_point` and `angle` are specific, not generic
- ✅ `whatsapp_draft` is under 400 characters
- ✅ `whatsapp_draft` does NOT start with "Hi, we offer..."
- ✅ `whatsapp_deep_link` opens WhatsApp with the message pre-filled
- ⚠️ If `phone_raw` is null for most leads → Google is stripping data. Add `PROXY_URL`.

---

## Step 8 — Daily Approval Workflow

Once the cron is active (2 AM IST daily):

1. **Morning check** (~8 AM): Go to Supabase → `approval_queue` view
2. Review each lead's `whatsapp_draft`
3. To edit a draft: `UPDATE leads SET whatsapp_draft = '...' WHERE id = '...'`
4. To approve: `UPDATE leads SET status = 'approved', approved_at = NOW() WHERE id = '...'`
5. To reject: `UPDATE leads SET status = 'rejected' WHERE id = '...'`
6. Open `whatsapp_deep_link` → one-tap send via WhatsApp Business app
7. After sending: `UPDATE leads SET status = 'sent', sent_at = NOW() WHERE id = '...'`

> **Phase 2 improvement**: Build a simple approval UI (Retool or Softr) that adds buttons for Approve/Reject/Send to avoid raw SQL. This is much faster for daily use.

---

## Step 9 — Activate the Daily Cron

Once the manual test produces good leads:

1. In n8n workflow → **Activate** (toggle top-right)
2. The workflow will now run every night at 2 AM IST automatically
3. You'll have a fresh batch of AI-drafted messages waiting by morning

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Scraper returns 0 leads | Google Maps bot detection | Add `PROXY_URL` env var with a residential proxy |
| `phone_raw` is null for all leads | Google stripped phone data | Same as above |
| Claude returns non-JSON | Rare model quirk | The parser handles this gracefully and sets confidence=low |
| n8n Postgres connection fails | SSL setting | Ensure SSL mode is set to "Require" in credentials |
| Railway deploy fails | Playwright deps | Check build logs — sometimes apt packages fail on first deploy |

---

## Phase 2 Checklist (Do after Phase 1 produces real sends & replies)

- [ ] Create Serper.dev account (Step 3)
- [ ] Create Apify account (Step 4)
- [ ] Add website enrichment node to n8n
- [ ] Add Serper.dev decision-maker lookup node
- [ ] Add Apify Meta Ads scraper node (India first)
- [ ] Expand query loop from 1 query to 30 (India) + 20 (international)
- [ ] Add residential proxy service (Bright Data / Smartproxy)
- [ ] Build approval UI (Retool/Softr) to replace raw SQL approvals
