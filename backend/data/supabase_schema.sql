-- Run this in Supabase SQL Editor (supabase.com → your project → SQL Editor)

create table if not exists deals (
  id              text primary key,         -- "{channel}_{message_id}"
  copy            text not null,            -- LLM-written deal copy
  platform        text,                     -- amazon, flipkart, myntra etc
  original_price  text,                     -- "₹2,990"
  deal_price      text,                     -- "₹899"
  coupon_code     text,                     -- "TIME2SAVE" or null
  affiliate_url   text,                     -- your affiliate link
  image_url       text,                     -- Supabase storage URL
  source_channel  text,                     -- Telegram channel name
  clicks          integer default 0,
  created_at      timestamptz default now()
);

-- Index for fast time-sorted queries (the main feed)
create index if not exists deals_created_at_idx on deals (created_at desc);

-- Storage bucket for deal images (run in Supabase Storage settings)
-- Create a public bucket called "deal-images"
