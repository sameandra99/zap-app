-- Pipeline logs table for analytics and audit trail
-- Stores all processed deals (posted + filtered)
CREATE TABLE IF NOT EXISTS pipeline_logs (
  id bigserial PRIMARY KEY,
  timestamp_fetched timestamp with time zone NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  archived_at timestamp with time zone,

  -- Message metadata
  raw_text text NOT NULL,
  source_channel text,

  -- Processing decision
  is_valid boolean NOT NULL,
  filter_reason text,

  -- Generated content (if valid)
  copy text,
  platform text,
  deal_price text,
  original_price text,
  coupon_code text,
  affiliate_url text,

  -- LLM response (stored as JSONB for flexibility)
  llm_decision jsonb,

  -- Admin override
  admin_approved boolean DEFAULT false,
  deal_id text,

  -- Image metadata
  image_url text,
  image_source text,

  -- Copy quality + URL tracking
  copy_quality_score integer,
  quality_reasons text,
  resolved_url text   -- resolved-but-not-cleaned intermediate (for Link Ops view)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_created_at ON pipeline_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_is_valid ON pipeline_logs(is_valid);
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_source_channel ON pipeline_logs(source_channel);
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_archived_at ON pipeline_logs(archived_at DESC);

-- Enable RLS (Row Level Security) - optional, disable if not needed
ALTER TABLE pipeline_logs ENABLE ROW LEVEL SECURITY;

-- Public read access (no write, only admin/service writes via service key)
CREATE POLICY "Allow public read" ON pipeline_logs
  FOR SELECT USING (true);
