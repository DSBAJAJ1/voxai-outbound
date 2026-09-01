-- ============================================================
-- VoxAI Outbound Lead Generation — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Master Leads Table ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS leads (
    -- Primary key
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Core business info (from scraper)
    business_name           TEXT NOT NULL,
    category                TEXT,
    phone_raw               TEXT,
    phone_normalized        TEXT,           -- E.164 format, e.g. +919876543210
    address                 TEXT,
    website                 TEXT,           -- nullable
    has_website             BOOLEAN NOT NULL DEFAULT FALSE,
    rating                  NUMERIC(3, 1),  -- e.g. 4.3
    review_count            INTEGER,

    -- Source metadata
    source                  TEXT NOT NULL CHECK (source IN ('gmaps', 'meta_ads')),
    region                  TEXT NOT NULL CHECK (region IN ('india', 'intl')),
    country                 TEXT NOT NULL CHECK (country IN ('IN', 'AE', 'QA', 'SA', 'SG')),
    preferred_language      TEXT NOT NULL DEFAULT 'english'
                                CHECK (preferred_language IN ('hinglish', 'english')),

    -- Meta Ads specific (nullable for gmaps source)
    ad_copy                 TEXT,
    original_ad_language    TEXT,           -- e.g. 'en', 'hi', 'ar'
    is_running_ads          BOOLEAN NOT NULL DEFAULT FALSE,

    -- Enrichment (Phase 2)
    website_text_excerpt    TEXT,           -- First ~2000 chars of website body
    has_chat_widget         BOOLEAN,        -- Intercom, Tawk.to, Crisp, etc.
    decision_maker_name     TEXT,           -- nullable
    decision_maker_linkedin TEXT,           -- URL, nullable

    -- AI outputs (Layer 4 — Pain-Point Detection)
    pain_point              TEXT,
    angle                   TEXT,
    confidence              TEXT CHECK (confidence IN ('high', 'medium', 'low')),

    -- AI outputs (Layer 5 — Message Drafting)
    whatsapp_draft          TEXT,
    linkedin_draft          TEXT,           -- nullable — only if DM LinkedIn found

    -- WhatsApp deep link (computed after phone_normalized is set)
    -- Format: https://wa.me/{phone_without_plus}?text={url_encoded_draft}
    -- This is set by the n8n workflow after both phone and draft are ready
    whatsapp_deep_link      TEXT,

    -- Pipeline status
    status                  TEXT NOT NULL DEFAULT 'pending_enrichment'
                                CHECK (status IN (
                                    'pending_enrichment',
                                    'pending_approval',
                                    'approved',
                                    'rejected',
                                    'edited',
                                    'sent',
                                    'replied',
                                    'hot_lead',
                                    'dead'
                                )),

    -- Record type (first outreach vs follow-up)
    record_type             TEXT NOT NULL DEFAULT 'outreach'
                                CHECK (record_type IN ('outreach', 'follow_up')),
    parent_lead_id          UUID REFERENCES leads(id), -- for follow_up records

    -- Timestamps
    scraped_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    enriched_at             TIMESTAMPTZ,
    approved_at             TIMESTAMPTZ,
    sent_at                 TIMESTAMPTZ,
    replied_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Follow-up tracking
    follow_up_count         INTEGER NOT NULL DEFAULT 0
);

-- ── Dedupe Duplicates Log Table ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dedupe_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name   TEXT,
    phone_raw       TEXT,
    country         TEXT,
    source          TEXT,
    reason          TEXT,           -- 'phone_match' | 'fuzzy_name_match'
    matched_lead_id UUID REFERENCES leads(id),
    discarded_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Scrape Run Log Table ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scrape_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL,  -- 'gmaps' | 'meta_ads'
    region          TEXT NOT NULL,
    query           TEXT,
    location        TEXT,
    country         TEXT,
    leads_found     INTEGER NOT NULL DEFAULT 0,
    leads_inserted  INTEGER NOT NULL DEFAULT 0,
    leads_deduped   INTEGER NOT NULL DEFAULT 0,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message   TEXT            -- null if successful
);

-- ── Indexes ────────────────────────────────────────────────────────────────

-- Fast dedupe lookups
CREATE INDEX IF NOT EXISTS idx_leads_phone_normalized_country
    ON leads (phone_normalized, country)
    WHERE phone_normalized IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_business_name_country
    ON leads (business_name, country);

-- Pipeline status filtering (approval queue, follow-up scheduler)
CREATE INDEX IF NOT EXISTS idx_leads_status
    ON leads (status);

-- Region + status (timezone-aware batch views)
CREATE INDEX IF NOT EXISTS idx_leads_region_status
    ON leads (region, status);

-- Follow-up scheduler: sent_at + follow_up_count
CREATE INDEX IF NOT EXISTS idx_leads_sent_followup
    ON leads (sent_at, follow_up_count)
    WHERE status = 'sent';

-- ── Auto-update updated_at trigger ────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ── Approval Queue View (replaces Airtable filtered view) ─────────────────

CREATE OR REPLACE VIEW approval_queue AS
SELECT
    id,
    business_name,
    category,
    region,
    country,
    phone_normalized,
    whatsapp_deep_link,
    pain_point,
    angle,
    confidence,
    whatsapp_draft,
    linkedin_draft,
    decision_maker_name,
    decision_maker_linkedin,
    status,
    record_type,
    scraped_at
FROM leads
WHERE status = 'pending_approval'
ORDER BY
    CASE confidence WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,
    region,
    scraped_at DESC;

-- ── Ready-to-Send Views (timezone batches) ─────────────────────────────────

CREATE OR REPLACE VIEW ready_india AS
SELECT
    id, business_name, category, phone_normalized, whatsapp_deep_link,
    whatsapp_draft, pain_point, status, approved_at
FROM leads
WHERE status = 'approved' AND region = 'india'
ORDER BY approved_at ASC;

CREATE OR REPLACE VIEW ready_international AS
SELECT
    id, business_name, category, country, phone_normalized, whatsapp_deep_link,
    whatsapp_draft, linkedin_draft, decision_maker_name, decision_maker_linkedin,
    pain_point, status, approved_at
FROM leads
WHERE status = 'approved' AND region = 'intl'
ORDER BY approved_at ASC;

-- ── Follow-up Due View (Layer 8) ───────────────────────────────────────────

CREATE OR REPLACE VIEW follow_up_due AS
SELECT
    id, business_name, category, region, country,
    phone_normalized, whatsapp_draft, pain_point, angle,
    sent_at, follow_up_count
FROM leads
WHERE
    status = 'sent'
    AND sent_at < NOW() - INTERVAL '3 days'
    AND follow_up_count < 3  -- Max 3 follow-ups per lead
ORDER BY sent_at ASC;
