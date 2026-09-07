# Rolling price poller — scope

The feed currently works by batch-and-drip: fetch everything that clears the
bar, queue it, release it a few per hour. That fills a bucket and empties it.
Freshness is an illusion the queue creates, and when the queue runs dry the feed
dies — which is what happened at 21:00 UTC on 6 September, nine hours before
anyone noticed.

This replaces it with a poller that publishes *price changes* as they happen.

## Why the current shape can't deliver "new every few minutes"

Measured 7 September against the 91-brand roster:

| | |
|---|---|
| qualifying deals available | 111 |
| already in the feed | 44 |
| **genuinely new** | **67** |
| brands producing anything | **18 of 91** |

At 8/hour (192/day) a 67-deal refill lasts 8.4 hours. At one every five minutes
(288/day) it lasts 5.6. The roster replenishes maybe 60–90/day. **The cadence
asked for is 3–5× what the catalogue produces**, so no scheduling change fixes
it — the supply model has to change.

## The insight

A *new product* is rare. A *price change* is not. Across ~146 live brands and
~20,000 in-stock variants, something moves every few minutes. Those moves are
real events, and a feed built on them is genuinely fresh rather than a queue
draining on a timer.

This is also the price-history job. The two are the same work: you cannot say
"this price dropped" without knowing what it was, and you cannot say "lowest in
90 days" without ninety days of observations. Every day the poller does not run
is a day of history that cannot be recovered.

## Shape

**A sweep, not a batch.** Cycle the roster continuously — a slice of brands
every few minutes — so the whole catalogue is covered every few hours and the
load is flat rather than spiky.

```
every 5 min:  take the next ~6 brands
              read their catalogue over UCP
              write one observation row per variant
              emit a deal for anything that dropped
```

At 146 brands and 6 per slice, a full sweep completes in about two hours.

**Store every observation, publish only the interesting ones.** Observations
are cheap and their value compounds. Publishing is a judgement and should stay
narrow.

### Tables

```sql
-- one row per variant per observation; the asset that accumulates
price_observations (
    variant_id   text,
    domain       text,
    price        integer,        -- paise, as UCP reports it
    list_price   integer,
    in_stock     boolean,
    observed_at  timestamptz,
    primary key (variant_id, observed_at)
)

-- current state per variant, so a sweep compares without scanning history
price_current (
    variant_id   text primary key,
    domain       text,
    title        text,
    image_url    text,
    price        integer,
    list_price   integer,
    in_stock     boolean,
    low_30d      integer,
    low_90d      integer,
    first_seen   timestamptz,
    last_seen    timestamptz
)
```

`price_observations` grows at roughly 20,000 rows per sweep. At a two-hour
sweep that is ~240k rows/day, ~90M/year — too much to keep raw. Roll up to
daily min/max/close per variant after 14 days; a day's low is all the history a
"lowest in 90 days" claim needs.

### What earns a place in the feed

A drop is publishable when **all** hold:

1. it fell at least ~5% against the last observation, and
2. it is at or near its own 30-day low, and
3. the brand passes the roster's existing quality rules, and
4. that variant has not been published in the last N days.

Rule 2 is what the current pipeline cannot do, and it is the whole point: it
compares against a price we watched, not against the merchant's list price. It
retires the MRP-theatre guard, the brand-relative bar and the discount floor —
all of which exist only because we had no history.

## What changes elsewhere

- **The drip disappears.** Deals publish when they happen. No queue, no drought.
- **`publish_at` stays** for editorial pacing during a quiet hour, not as the
  primary mechanism.
- **Auto-push gets a real signal.** "Back at its lowest since June" is worth a
  notification in a way "we just found this" never was.
- **The watchlist becomes possible.** Watching a product is only meaningful
  against observed history.

## Cost

One always-on Fly machine, 512MB, ~$4/month. Roughly 20k UCP reads per sweep
spread over two hours — about 3 requests/second across 146 domains, which is
politer than the current burst of 450 calls in 40 seconds.

Supabase storage is the real cost and is controlled by the rollup above.

## Build order

1. Tables + the sweep loop writing `price_observations` and `price_current`.
   **Publish nothing.** Let it run and watch what the data looks like.
2. After ~7 days, check the real change rate: how many drops per hour, how deep,
   which brands actually move. That number decides the publish thresholds — do
   not guess them now.
3. Turn on publishing with rules tuned to that measurement.
4. Retire the batch ingest.

Step 1 is the only urgent part. It is worth starting before the publish rules
are settled, because the history it accumulates cannot be backfilled and every
later decision depends on having it.

## Operational notes for the stopgap now running

`ucp-ingest` is a Fly scheduled machine on the `loot-api` app, region `sin`,
512MB, running hourly:

```
sh -lc "cd /app && python pipeline/ucp_ingest.py --per-hour 4"
```

Two traps found while setting it up:

- **`fly deploy` does NOT update a scheduled machine.** It is pinned to the
  image digest it was created with, so a deploy leaves it running stale code
  silently. After any backend deploy:
  `fly machine update <id> -a loot-api --image registry.fly.io/loot-api:<new-tag> --yes`
- **`fly machine run IMAGE sh -c "..."` swallows the command.** flyctl parses
  the args as its own flags and the machine runs a bare `sh` that exits
  immediately with code 0 — a silent no-op that looks like success. Use `--`
  before the command.

Also: region `bom` is now deprecated on Fly and refuses new resources, even
though `fly.api.toml` still declares it as the primary region. The app has been
running in `sin` regardless.

## Open questions

- **Roster width.** 91 curated brands, or all 146 live? Wider gives more events
  and better history; the curation still governs what publishes.
- **Sweep period.** Two hours is a guess. Step 2 will show whether prices move
  fast enough to justify it or whether six hours is plenty.
- **Variant vs product.** Observations are per variant. Deals are per product.
  A size selling out is a signal too, and this is where it would come from.
