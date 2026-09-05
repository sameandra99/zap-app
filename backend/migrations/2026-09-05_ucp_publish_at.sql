-- Scheduled release for D2C (UCP) deals. The ingest pulls a whole brand's
-- eligible catalogue in one pass, but dumping 300+ cards at once floods the feed
-- and spends the entire inventory in a single scroll. publish_at lets the ingest
-- stage everything and drip it into the feed a few per hour.
--
-- Additive and nullable on purpose: every existing row keeps publish_at NULL and
-- the feed treats NULL as "already published", so scraped deals are untouched.
ALTER TABLE deals ADD COLUMN IF NOT EXISTS publish_at timestamptz;

-- The feed asks "published yet, newest first" on every page load.
CREATE INDEX IF NOT EXISTS idx_deals_publish_at_created
  ON deals (publish_at, created_at DESC);
