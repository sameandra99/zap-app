-- App tab configuration — lets the mobile app render its filter tabs from the
-- backend so they can be enabled/disabled, reordered, and relabelled without an
-- app release. The app ships a hardcoded fallback identical to the seed below,
-- so a missing/unreachable table never leaves the app tab-less.
--
-- type semantics (the app maps these to its existing filter logic):
--   'all'      → every deal (the default "Latest" feed)
--   'hot'      → only deals where pinned = true (admin-curated, see /admin Pin)
--   'category' → deals whose inferred category == value (e.g. 'electronics')
CREATE TABLE IF NOT EXISTS app_tabs (
  key        text PRIMARY KEY,
  label      text NOT NULL,
  type       text NOT NULL DEFAULT 'category',  -- 'all' | 'hot' | 'category'
  value      text,                              -- category key when type='category'
  position   int  NOT NULL DEFAULT 0,
  enabled    boolean NOT NULL DEFAULT true,
  updated_at timestamptz DEFAULT now()
);

-- Seed the current tab set (idempotent — re-running won't clobber edits).
INSERT INTO app_tabs (key, label, type, value, position, enabled) VALUES
  ('latest',      'Latest',      'all',      NULL,          0, true),
  ('hot',         '🔥 Hot',      'hot',      NULL,          1, true),
  ('electronics', 'Electronics', 'category', 'electronics', 2, true),
  ('fashion',     'Fashion',     'category', 'fashion',     3, true),
  ('footwear',    'Footwear',    'category', 'footwear',    4, true),
  ('beauty',      'Beauty',      'category', 'beauty',      5, true),
  ('home',        'Home',        'category', 'home',        6, true),
  ('sports',      'Sports',      'category', 'sports',      7, true),
  ('grocery',     'Grocery',     'category', 'grocery',     8, true)
ON CONFLICT (key) DO NOTHING;

-- Public read (the app fetches this with the anon key); writes only via service role.
ALTER TABLE app_tabs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "app_tabs public read" ON app_tabs;
CREATE POLICY "app_tabs public read" ON app_tabs
  FOR SELECT USING (true);

DROP POLICY IF EXISTS "app_tabs service write" ON app_tabs;
CREATE POLICY "app_tabs service write" ON app_tabs
  FOR ALL USING (auth.role() = 'service_role');
