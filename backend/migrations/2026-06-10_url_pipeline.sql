-- ════════════════════════════════════════════════════════════════════════
-- URL pipeline upgrade — run this whole file once in Supabase SQL Editor.
-- Safe to re-run (uses IF NOT EXISTS / ON CONFLICT).
-- ════════════════════════════════════════════════════════════════════════

-- 1. Add the resolved-URL column to pipeline_logs (for the Link Ops 3-col view)
ALTER TABLE pipeline_logs ADD COLUMN IF NOT EXISTS resolved_url text;
ALTER TABLE pipeline_logs ADD COLUMN IF NOT EXISTS copy_quality_score integer;
ALTER TABLE pipeline_logs ADD COLUMN IF NOT EXISTS quality_reasons text;

-- 2. Redirect-domain approval registry
CREATE TABLE IF NOT EXISTS redirect_domains (
  domain      text PRIMARY KEY,
  status      text NOT NULL DEFAULT 'pending',   -- pending | approved | blocked
  first_seen  timestamptz DEFAULT now(),
  last_seen   timestamptz DEFAULT now(),
  seen_count  integer DEFAULT 1,
  sample_url  text
);

CREATE INDEX IF NOT EXISTS idx_redirect_domains_status ON redirect_domains(status);

-- Seed currently-trusted trackers as approved
INSERT INTO redirect_domains (domain, status, sample_url) VALUES
  ('ajiio.co',        'approved', 'https://ajiio.co/...'),
  ('amzn-to.co',      'approved', 'https://amzn-to.co/...'),
  ('amzn.urlgeni.us', 'approved', 'https://amzn.urlgeni.us/...'),
  ('fkrt.co',         'approved', 'https://fkrt.co/...'),
  ('fkrt.cc',         'approved', 'https://fkrt.cc/...'),
  ('myntr.in',        'approved', 'https://myntr.in/...'),
  ('myntr.it',        'approved', 'https://myntr.it/...'),
  ('linkredirect.in', 'approved', 'https://linkredirect.in/...'),
  ('dl.flipkart.com', 'approved', 'https://dl.flipkart.com/...'),
  ('amzn.to',         'approved', 'https://amzn.to/...'),
  ('ddime.in',        'approved', 'https://ddime.in/...')
ON CONFLICT (domain) DO NOTHING;

-- RLS: public read, service-role write
ALTER TABLE redirect_domains ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "redirect_domains read" ON redirect_domains;
CREATE POLICY "redirect_domains read" ON redirect_domains
  FOR SELECT USING (true);

DROP POLICY IF EXISTS "redirect_domains service write" ON redirect_domains;
CREATE POLICY "redirect_domains service write" ON redirect_domains
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
