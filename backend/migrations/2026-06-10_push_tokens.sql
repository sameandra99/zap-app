-- Push tokens table — persists device tokens across API restarts
CREATE TABLE IF NOT EXISTS push_tokens (
  token       text PRIMARY KEY,
  created_at  timestamptz DEFAULT now(),
  last_seen   timestamptz DEFAULT now()
);

-- Public insert (app registers its own token), no read (privacy)
ALTER TABLE push_tokens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "push_tokens insert" ON push_tokens;
CREATE POLICY "push_tokens insert" ON push_tokens
  FOR INSERT WITH CHECK (true);

DROP POLICY IF EXISTS "push_tokens service read" ON push_tokens;
CREATE POLICY "push_tokens service read" ON push_tokens
  FOR SELECT USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "push_tokens service upsert" ON push_tokens;
CREATE POLICY "push_tokens service upsert" ON push_tokens
  FOR ALL USING (auth.role() = 'service_role');
