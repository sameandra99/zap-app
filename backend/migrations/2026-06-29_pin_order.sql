-- Adds explicit ordering for pinned (Hot) deals.
-- pin_order is an integer that admin sets via the Hot Deals panel.
-- Lower value = shown first. NULL means no explicit rank (new pins go to the end).
ALTER TABLE deals ADD COLUMN IF NOT EXISTS pin_order integer;

CREATE INDEX IF NOT EXISTS deals_pin_order_idx ON deals (pin_order) WHERE pinned = true;
