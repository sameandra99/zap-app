-- Add copy quality tracking columns to pipeline_logs
-- Allows analysis of what percentage of posts are preserved vs rewritten

ALTER TABLE pipeline_logs
ADD COLUMN IF NOT EXISTS copy_quality_score smallint CHECK (copy_quality_score >= 1 AND copy_quality_score <= 10),
ADD COLUMN IF NOT EXISTS quality_reasons text;

-- Index for quality analysis queries
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_quality_score ON pipeline_logs(copy_quality_score DESC);

-- Index for finding high-quality original copies (preserved)
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_quality_high ON pipeline_logs(copy_quality_score DESC)
WHERE copy_quality_score >= 7;
