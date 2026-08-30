-- Push notification effectiveness — the data needed to answer "did that change
-- help?". Until now a notification tap was indistinguishable from a browse tap
-- (deals.clicks has no source), so push CTR could not be measured at all.
--
-- Two event kinds, one table:
--   'sent' — one row per push delivery wave, count = devices it reached
--   'open' — one row per notification tap
-- CTR for any period = sum(count) where event='open' / sum(count) where 'sent'.
CREATE TABLE IF NOT EXISTS push_events (
  id         bigserial PRIMARY KEY,
  deal_id    text,
  event      text NOT NULL CHECK (event IN ('sent', 'open')),
  count      integer NOT NULL DEFAULT 1,
  variant    text,          -- e.g. 'image' | 'noimage', so A/B arms stay separable
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS push_events_event_time_idx ON push_events (event, created_at DESC);
CREATE INDEX IF NOT EXISTS push_events_deal_idx ON push_events (deal_id, created_at DESC);
