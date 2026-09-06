-- Editor-curated product lists ("Studs and hoops for work", "Bags that fit a
-- laptop"). These are hand-built in the admin, not derived from the deal feed:
-- the whole point is that a person chose nine things out of thirteen thousand.
--
-- Deliberately separate from `deals`. A deal is a moment (this price, today); a
-- list item is an opinion about a product that outlives any particular price,
-- and the same product can sit in several lists at once.

CREATE TABLE IF NOT EXISTS curated_lists (
    id          text PRIMARY KEY,                  -- slug, e.g. 'work-jewellery'
    title       text NOT NULL,
    blurb       text,
    curator     text NOT NULL DEFAULT 'deskdays',  -- handle key, see curators below
    position    integer NOT NULL DEFAULT 0,
    published   boolean NOT NULL DEFAULT false,    -- draft until an editor says so
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Seeded in-house accounts. Real curators can be added later without a schema
-- change; the app only needs a handle and a mark.
CREATE TABLE IF NOT EXISTS curators (
    key    text PRIMARY KEY,
    handle text NOT NULL,
    bio    text,
    glyph  text NOT NULL DEFAULT 'desk'            -- desk | moon | arch | sun
);

INSERT INTO curators (key, handle, bio, glyph) VALUES
    ('deskdays',   '@deskdays',   'Nine-to-six, and after',  'desk'),
    ('afterhours', '@afterhours', 'For the evening',         'moon'),
    ('roomtone',   '@roomtone',   'Things for the house',    'arch'),
    ('packlight',  '@packlight',  'Travel and warm weather', 'sun')
ON CONFLICT (key) DO NOTHING;

-- One row per product in a list. The product fields are denormalised on
-- purpose: a merchant can pull a product from its catalogue at any time, and a
-- list that silently loses items is worse than one showing a stale price. The
-- refresh job updates price/availability in place and flags what has gone.
CREATE TABLE IF NOT EXISTS curated_list_items (
    id             bigserial PRIMARY KEY,
    list_id        text NOT NULL REFERENCES curated_lists(id) ON DELETE CASCADE,
    variant_id     text,                           -- gid://shopify/ProductVariant/…
    product_url    text NOT NULL,
    domain         text NOT NULL,
    brand          text,
    title          text,
    image_url      text,
    price          integer,                        -- paise, as UCP reports it
    list_price     integer,
    currency       text NOT NULL DEFAULT 'INR',
    in_stock       boolean NOT NULL DEFAULT true,
    position       integer NOT NULL DEFAULT 0,
    added_by       text NOT NULL DEFAULT 'admin',  -- 'admin' or a user id later
    checked_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- The same product must not appear twice in one list. product_url rather than
-- variant_id because a URL is what an editor pastes, and not every store
-- resolves to a variant id on the first try.
CREATE UNIQUE INDEX IF NOT EXISTS uq_list_item
    ON curated_list_items (list_id, product_url);

CREATE INDEX IF NOT EXISTS idx_list_items_list
    ON curated_list_items (list_id, position);

CREATE INDEX IF NOT EXISTS idx_lists_published
    ON curated_lists (published, position);
