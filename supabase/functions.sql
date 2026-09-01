-- ============================================================
-- VoxAI — Supabase Fuzzy Dedupe Functions
-- Run this AFTER schema.sql in Supabase SQL Editor
-- ============================================================

-- Enable trigram extension for fuzzy string matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Fuzzy Business Name Dedupe Function ───────────────────────────────────────
-- Returns the most similar existing lead (if similarity >= threshold)
-- Used by n8n as a secondary dedupe check when phone numbers differ.

CREATE OR REPLACE FUNCTION find_fuzzy_name_match(
    p_business_name TEXT,
    p_country       TEXT,
    p_threshold     FLOAT DEFAULT 0.75
)
RETURNS TABLE (
    lead_id         UUID,
    business_name   TEXT,
    similarity_score FLOAT
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        id                                          AS lead_id,
        business_name,
        similarity(lower(business_name), lower(p_business_name)) AS similarity_score
    FROM leads
    WHERE
        country = p_country
        AND similarity(lower(business_name), lower(p_business_name)) >= p_threshold
    ORDER BY similarity_score DESC
    LIMIT 1;
$$;

-- ── Helper: Check duplicate by phone OR fuzzy name ────────────────────────────
-- Returns a JSON object describing whether a duplicate was found and why.
-- n8n calls this as a single SQL query to handle both dedupe checks at once.

CREATE OR REPLACE FUNCTION check_lead_duplicate(
    p_phone_normalized  TEXT,
    p_business_name     TEXT,
    p_country           TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    phone_match_id   UUID;
    fuzzy_match_id   UUID;
    fuzzy_score      FLOAT;
BEGIN
    -- 1. Exact phone match (primary check)
    IF p_phone_normalized IS NOT NULL AND p_phone_normalized != '' THEN
        SELECT id INTO phone_match_id
        FROM leads
        WHERE phone_normalized = p_phone_normalized
          AND country = p_country
        LIMIT 1;

        IF phone_match_id IS NOT NULL THEN
            RETURN jsonb_build_object(
                'is_duplicate', true,
                'reason', 'phone_match',
                'matched_lead_id', phone_match_id
            );
        END IF;
    END IF;

    -- 2. Fuzzy name match (secondary check)
    SELECT lead_id, similarity_score
    INTO fuzzy_match_id, fuzzy_score
    FROM find_fuzzy_name_match(p_business_name, p_country, 0.78);

    IF fuzzy_match_id IS NOT NULL THEN
        RETURN jsonb_build_object(
            'is_duplicate', true,
            'reason', 'fuzzy_name_match',
            'matched_lead_id', fuzzy_match_id,
            'similarity_score', fuzzy_score
        );
    END IF;

    -- 3. Not a duplicate
    RETURN jsonb_build_object('is_duplicate', false);
END;
$$;

-- ── Index for pg_trgm similarity queries ──────────────────────────────────────
-- GIN index dramatically speeds up similarity() queries on large tables.

CREATE INDEX IF NOT EXISTS idx_leads_business_name_trgm
    ON leads USING gin (lower(business_name) gin_trgm_ops);

-- ── Test the function (run manually to verify) ────────────────────────────────
-- SELECT check_lead_duplicate('+919876543210', 'Test Business', 'IN');
-- SELECT find_fuzzy_name_match('Singh Coaching Centre', 'IN', 0.75);
