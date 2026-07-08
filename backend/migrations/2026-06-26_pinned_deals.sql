-- Add a `pinned` flag to deals so admins can curate "Trending" deals that float
-- to the top of the feed. Safe + additive: nullable with a false default, so the
-- live API (which doesn't yet sort on it) is completely unaffected until deployed.
ALTER TABLE deals ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false;

-- Speeds up the "pinned first, then newest" ordering the /deals endpoint uses.
CREATE INDEX IF NOT EXISTS idx_deals_pinned_created
  ON deals (pinned DESC, created_at DESC);

-- Discount percentage off (e.g. 57 = 57% off). The pipeline already references
-- this field in the deal insert (save_to_db spreads the whole dict), so this
-- column MUST exist before deploying the current pipeline or every save 400s.
-- Populated from the scraped Amazon product page (the "true" discount) when
-- available, falling back to the LLM-extracted value from the deal message.
ALTER TABLE deals ADD COLUMN IF NOT EXISTS discount_pct integer;
