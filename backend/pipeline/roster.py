"""Curated brand roster — the editorial position behind the feed.

Two independent axes, agreed with the product owner:

  traction     does India already buy this brand?      (assigned by hand; UCP
                                                        carries no revenue data
                                                        and the global catalog's
                                                        review counts resolve
                                                        non-deterministically —
                                                        10, 17 and 34 of 88
                                                        brands on three runs of
                                                        the same query)
  product pull would the product alone stop a scroll?  (editorial, evidenced by
                                                        the price architecture
                                                        measured below)

  A  proven + pull    the anchors; admit on a modest offer
  B  pull, small      the discovery engine; admit on a real offer
  C  proven, no pull  volume brands; admit ONLY on a top-decile offer

`measured` is a snapshot from 13,581 in-stock INR variants across 146 live
stores, taken 2026-09-05. It is evidence for the tiering, not a runtime input —
the pipeline re-measures each run.

Two disqualifiers found while building this, both silent:
  * Vahdam and Kalki price in USD for agents and ignore every currency hint the
    protocol offers (catalog.context, top-level context, buyer.address,
    catalog.currency all return USD). Excluded — an INR feed cannot use them.
  * A manifest at /.well-known/ucp does not imply a usable catalog: 82°E, Aulerth
    and Fire-Boltt advertise catalog.search and return nothing.
"""

ROSTER = {
    "mokobara.com": {
        "quadrant": "A",
        "label": "Mokobara",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 120,
            "median_price": 6699,
            "p90_price": 11999,
            "premium_share": 85,
            "discount_rate": 99,
            "median_discount": 41,
            "p80_discount": 50
        }
    },
    "www.nappadori.com": {
        "quadrant": "A",
        "label": "Nappa Dori",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 120,
            "median_price": 16000,
            "p90_price": 32000,
            "premium_share": 95,
            "discount_rate": 10,
            "median_discount": 14,
            "p80_discount": 0
        }
    },
    "nicobar.com": {
        "quadrant": "A",
        "label": "Nicobar",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 120,
            "median_price": 6550,
            "p90_price": 10500,
            "premium_share": 99,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "www.safaribags.com": {
        "quadrant": "A",
        "label": "Safari",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 91,
            "median_price": 4799,
            "p90_price": 7799,
            "premium_share": 85,
            "discount_rate": 87,
            "median_discount": 30,
            "p80_discount": 50
        }
    },
    "www.superkicks.in": {
        "quadrant": "A",
        "label": "Superkicks",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 88,
            "median_price": 8960,
            "p90_price": 13599,
            "premium_share": 94,
            "discount_rate": 44,
            "median_discount": 30,
            "p80_discount": 30
        }
    },
    "www.hidesign.com": {
        "quadrant": "A",
        "label": "Hidesign",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 117,
            "median_price": 8956,
            "p90_price": 23995,
            "premium_share": 84,
            "discount_rate": 35,
            "median_discount": 30,
            "p80_discount": 30
        }
    },
    "www.limitededt.in": {
        "quadrant": "A",
        "label": "Limited Edt",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 81,
            "median_price": 10999,
            "p90_price": 17999,
            "premium_share": 94,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "thehouseofrare.com": {
        "quadrant": "A",
        "label": "Rare Rabbit",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 120,
            "median_price": 2262,
            "p90_price": 4674,
            "premium_share": 42,
            "discount_rate": 85,
            "median_discount": 40,
            "p80_discount": 45
        }
    },
    "snitch.co.in": {
        "quadrant": "C",
        "label": "Snitch",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 118,
            "median_price": 1279,
            "p90_price": 2624,
            "premium_share": 14,
            "discount_rate": 50,
            "median_discount": 20,
            "p80_discount": 20
        }
    },
    "giva.co": {
        "quadrant": "A",
        "label": "GIVA",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 116,
            "median_price": 2999,
            "p90_price": 8299,
            "premium_share": 56,
            "discount_rate": 100,
            "median_discount": 47,
            "p80_discount": 53
        }
    },
    "thesleepcompany.in": {
        "quadrant": "A",
        "label": "The Sleep Company",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 33,
            "median_price": 2999,
            "p90_price": 57990,
            "premium_share": 58,
            "discount_rate": 100,
            "median_discount": 39,
            "p80_discount": 47
        }
    },
    "nestasia.in": {
        "quadrant": "A",
        "label": "Nestasia",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 119,
            "median_price": 1399,
            "p90_price": 3250,
            "premium_share": 15,
            "discount_rate": 94,
            "median_discount": 28,
            "p80_discount": 36
        }
    },
    "www.chumbak.com": {
        "quadrant": "A",
        "label": "Chumbak",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 120,
            "median_price": 1334,
            "p90_price": 61246,
            "premium_share": 26,
            "discount_rate": 69,
            "median_discount": 30,
            "p80_discount": 30
        }
    },
    "suta.in": {
        "quadrant": "A",
        "label": "Suta",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 117,
            "median_price": 2800,
            "p90_price": 4250,
            "premium_share": 66,
            "discount_rate": 1,
            "median_discount": 12,
            "p80_discount": 0
        }
    },
    "thelabellife.com": {
        "quadrant": "A",
        "label": "The Label Life",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 65,
            "median_price": 2242,
            "p90_price": 3690,
            "premium_share": 31,
            "discount_rate": 71,
            "median_discount": 35,
            "p80_discount": 40
        }
    },
    "blissclub.com": {
        "quadrant": "C",
        "label": "BlissClub",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 40,
            "median_price": 1199,
            "p90_price": 1999,
            "premium_share": 0,
            "discount_rate": 100,
            "median_discount": 23,
            "p80_discount": 31
        }
    },
    "levi.in": {
        "quadrant": "A",
        "label": "Levi's",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 115,
            "median_price": 1923,
            "p90_price": 4299,
            "premium_share": 32,
            "discount_rate": 71,
            "median_discount": 48,
            "p80_discount": 55
        }
    },
    "nashermiles.com": {
        "quadrant": "C",
        "label": "Nasher Miles",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 120,
            "median_price": 2699,
            "p90_price": 6999,
            "premium_share": 52,
            "discount_rate": 99,
            "median_discount": 71,
            "p80_discount": 77
        }
    },
    "ugaoo.com": {
        "quadrant": "A",
        "label": "Ugaoo",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 118,
            "median_price": 1184,
            "p90_price": 2499,
            "premium_share": 8,
            "discount_rate": 69,
            "median_discount": 29,
            "p80_discount": 38
        }
    },
    "neemans.com": {
        "quadrant": "A",
        "label": "Neeman's",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 90,
            "median_price": 1499,
            "p90_price": 2599,
            "premium_share": 14,
            "discount_rate": 100,
            "median_discount": 46,
            "p80_discount": 65
        }
    },
    "ellementry.com": {
        "quadrant": "A",
        "label": "Ellementry",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 119,
            "median_price": 2050,
            "p90_price": 6650,
            "premium_share": 39,
            "discount_rate": 12,
            "median_discount": 20,
            "p80_discount": 0
        }
    },
    "www.thedecorkart.com": {
        "quadrant": "A",
        "label": "The Decor Kart",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 120,
            "median_price": 2680,
            "p90_price": 13242,
            "premium_share": 52,
            "discount_rate": 88,
            "median_discount": 40,
            "p80_discount": 40
        }
    },
    "aachho.com": {
        "quadrant": "A",
        "label": "Aachho",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 120,
            "median_price": 1864,
            "p90_price": 14591,
            "premium_share": 28,
            "discount_rate": 82,
            "median_discount": 60,
            "p80_discount": 65
        }
    },
    "okhai.org": {
        "quadrant": "A",
        "label": "Okhai",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 120,
            "median_price": 3540,
            "p90_price": 10350,
            "premium_share": 88,
            "discount_rate": 13,
            "median_discount": 28,
            "p80_discount": 0
        }
    },
    "isharya.com": {
        "quadrant": "A",
        "label": "Isharya",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 120,
            "median_price": 4999,
            "p90_price": 8499,
            "premium_share": 92,
            "discount_rate": 5,
            "median_discount": 45,
            "p80_discount": 0
        }
    },
    "zariin.com": {
        "quadrant": "A",
        "label": "Zariin",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 120,
            "median_price": 4499,
            "p90_price": 6999,
            "premium_share": 100,
            "discount_rate": 8,
            "median_discount": 15,
            "p80_discount": 0
        }
    },
    "bluetokaicoffee.com": {
        "quadrant": "C",
        "label": "Blue Tokai",
        "category": "food",
        "queries": [
            "coffee",
            "snack",
            "chocolate"
        ],
        "measured": {
            "n": 71,
            "median_price": 700,
            "p90_price": 1379,
            "premium_share": 1,
            "discount_rate": 10,
            "median_discount": 5,
            "p80_discount": 0
        }
    },
    "fizzygoblet.com": {
        "quadrant": "A",
        "label": "Fizzy Goblet",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 90,
            "median_price": 3592,
            "p90_price": 4990,
            "premium_share": 91,
            "discount_rate": 30,
            "median_discount": 40,
            "p80_discount": 20
        }
    },
    "urbanmonkey.com": {
        "quadrant": "A",
        "label": "Urban Monkey",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 73,
            "median_price": 1500,
            "p90_price": 2850,
            "premium_share": 19,
            "discount_rate": 44,
            "median_discount": 40,
            "p80_discount": 40
        }
    },
    "thepostbox.in": {
        "quadrant": "A",
        "label": "The Postbox",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 115,
            "median_price": 6799,
            "p90_price": 11650,
            "premium_share": 76,
            "discount_rate": 2,
            "median_discount": 10,
            "p80_discount": 0
        }
    },
    "huemn.in": {
        "quadrant": "B",
        "label": "Huemn",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 119,
            "median_price": 9500,
            "p90_price": 25500,
            "premium_share": 100,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "almostgods.com": {
        "quadrant": "B",
        "label": "Almost Gods",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 80,
            "median_price": 7500,
            "p90_price": 15500,
            "premium_share": 100,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "bluorng.com": {
        "quadrant": "B",
        "label": "BLUORNG",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 102,
            "median_price": 6300,
            "p90_price": 15000,
            "premium_share": 100,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "jaywalking.in": {
        "quadrant": "B",
        "label": "Jaywalking",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 119,
            "median_price": 6500,
            "p90_price": 40000,
            "premium_share": 100,
            "discount_rate": 17,
            "median_discount": 67,
            "p80_discount": 0
        }
    },
    "andamen.com": {
        "quadrant": "B",
        "label": "Andamen",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 120,
            "median_price": 5599,
            "p90_price": 6999,
            "premium_share": 97,
            "discount_rate": 18,
            "median_discount": 2,
            "p80_discount": 0
        }
    },
    "cordstudio.in": {
        "quadrant": "B",
        "label": "Cord",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 114,
            "median_price": 14500,
            "p90_price": 21200,
            "premium_share": 100,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "doodlage.in": {
        "quadrant": "B",
        "label": "Doodlage",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 90,
            "median_price": 7500,
            "p90_price": 10000,
            "premium_share": 87,
            "discount_rate": 23,
            "median_discount": 50,
            "p80_discount": 50
        }
    },
    "www.houseofmasaba.com": {
        "quadrant": "B",
        "label": "House of Masaba",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 119,
            "median_price": 29750,
            "p90_price": 100000,
            "premium_share": 100,
            "discount_rate": 29,
            "median_discount": 15,
            "p80_discount": 15
        }
    },
    "bunaai.com": {
        "quadrant": "B",
        "label": "Bunaai",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 119,
            "median_price": 3400,
            "p90_price": 4500,
            "premium_share": 89,
            "discount_rate": 51,
            "median_discount": 21,
            "p80_discount": 22
        }
    },
    "mishodesigns.com": {
        "quadrant": "B",
        "label": "Misho",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 120,
            "median_price": 11374,
            "p90_price": 22269,
            "premium_share": 100,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "outhouse-jewellery.com": {
        "quadrant": "B",
        "label": "Outhouse",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 120,
            "median_price": 10500,
            "p90_price": 26950,
            "premium_share": 100,
            "discount_rate": 8,
            "median_discount": 40,
            "p80_discount": 0
        }
    },
    "studiometallurgy.com": {
        "quadrant": "B",
        "label": "Studio Metallurgy",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 120,
            "median_price": 7650,
            "p90_price": 15500,
            "premium_share": 98,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "quirksmith.com": {
        "quadrant": "B",
        "label": "Quirksmith",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 113,
            "median_price": 3850,
            "p90_price": 12650,
            "premium_share": 65,
            "discount_rate": 88,
            "median_discount": 15,
            "p80_discount": 17
        }
    },
    "theindianethnicco.com": {
        "quadrant": "B",
        "label": "The Indian Ethnic Co",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 120,
            "median_price": 4250,
            "p90_price": 6950,
            "premium_share": 81,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "ikkis.in": {
        "quadrant": "B",
        "label": "Ikkis",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 48,
            "median_price": 8000,
            "p90_price": 16500,
            "premium_share": 96,
            "discount_rate": 6,
            "median_discount": 20,
            "p80_discount": 0
        }
    },
    "addresshome.com": {
        "quadrant": "B",
        "label": "Address Home",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 120,
            "median_price": 4990,
            "p90_price": 19990,
            "premium_share": 98,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "freedomtree.in": {
        "quadrant": "B",
        "label": "Freedom Tree",
        "category": "home",
        "queries": [
            "vase",
            "cushion",
            "tray",
            "lamp"
        ],
        "measured": {
            "n": 120,
            "median_price": 1880,
            "p90_price": 8370,
            "premium_share": 31,
            "discount_rate": 17,
            "median_discount": 50,
            "p80_discount": 0
        }
    },
    "gullylabs.com": {
        "quadrant": "B",
        "label": "Gully Labs",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 89,
            "median_price": 3990,
            "p90_price": 5990,
            "premium_share": 93,
            "discount_rate": 2,
            "median_discount": 14,
            "p80_discount": 0
        }
    },
    "paaduks.com": {
        "quadrant": "B",
        "label": "Paaduks",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 70,
            "median_price": 2490,
            "p90_price": 3290,
            "premium_share": 36,
            "discount_rate": 70,
            "median_discount": 37,
            "p80_discount": 51
        }
    },
    "crepdogcrew.com": {
        "quadrant": "B",
        "label": "Crepdog Crew",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 89,
            "median_price": 15749,
            "p90_price": 27499,
            "premium_share": 100,
            "discount_rate": 99,
            "median_discount": 17,
            "p80_discount": 23
        }
    },
    "tresmode.com": {
        "quadrant": "B",
        "label": "Tresmode",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 90,
            "median_price": 1499,
            "p90_price": 3750,
            "premium_share": 22,
            "discount_rate": 92,
            "median_discount": 75,
            "p80_discount": 82
        }
    },
    "assemblytravel.com": {
        "quadrant": "B",
        "label": "Assembly",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 105,
            "median_price": 2799,
            "p90_price": 6999,
            "premium_share": 70,
            "discount_rate": 100,
            "median_discount": 38,
            "p80_discount": 47
        }
    },
    "zouk.co.in": {
        "quadrant": "B",
        "label": "Zouk",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 59,
            "median_price": 1649,
            "p90_price": 3299,
            "premium_share": 19,
            "discount_rate": 27,
            "median_discount": 34,
            "p80_discount": 33
        }
    },
    "nasoprofumi.com": {
        "quadrant": "B",
        "label": "Naso Profumi",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 30,
            "median_price": 2500,
            "p90_price": 5500,
            "premium_share": 70,
            "discount_rate": 37,
            "median_discount": 55,
            "p80_discount": 55
        }
    },
    "bombaysweetshop.com": {
        "quadrant": "B",
        "label": "Bombay Sweet Shop",
        "category": "food",
        "queries": [
            "coffee",
            "snack",
            "chocolate"
        ],
        "measured": {
            "n": 70,
            "median_price": 418,
            "p90_price": 1500,
            "premium_share": 7,
            "discount_rate": 36,
            "median_discount": 11,
            "p80_discount": 11
        }
    },
    "manamchocolate.com": {
        "quadrant": "B",
        "label": "Manam",
        "category": "food",
        "queries": [
            "coffee",
            "snack",
            "chocolate"
        ],
        "measured": {
            "n": 90,
            "median_price": 785,
            "p90_price": 2920,
            "premium_share": 13,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "subko.coffee": {
        "quadrant": "B",
        "label": "Subko",
        "category": "food",
        "queries": [
            "coffee",
            "snack",
            "chocolate"
        ],
        "measured": {
            "n": 78,
            "median_price": 395,
            "p90_price": 950,
            "premium_share": 3,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "tjori.com": {
        "quadrant": "B",
        "label": "Tjori",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 120,
            "median_price": 1699,
            "p90_price": 3999,
            "premium_share": 14,
            "discount_rate": 96,
            "median_discount": 36,
            "p80_discount": 67
        }
    },
    "studiorigu.com": {
        "quadrant": "B",
        "label": "Studio Rigu",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 110,
            "median_price": 15500,
            "p90_price": 19610,
            "premium_share": 100,
            "discount_rate": 12,
            "median_discount": 24,
            "p80_discount": 0
        }
    },
    "bombaypaperie.com": {
        "quadrant": "B",
        "label": "Bombay Paperie",
        "category": "bags",
        "queries": [
            "backpack",
            "luggage",
            "bag",
            "wallet"
        ],
        "measured": {
            "n": 21,
            "median_price": 200,
            "p90_price": 1800,
            "premium_share": 5,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "letshyphen.com": {
        "quadrant": "C",
        "label": "Hyphen",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 92,
            "median_price": 587,
            "p90_price": 1043,
            "premium_share": 0,
            "discount_rate": 21,
            "median_discount": 5,
            "p80_discount": 0
        }
    },
    "beminimalist.co": {
        "quadrant": "C",
        "label": "Minimalist",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 114,
            "median_price": 360,
            "p90_price": 1019,
            "premium_share": 0,
            "discount_rate": 98,
            "median_discount": 10,
            "p80_discount": 10
        }
    },
    "dotandkey.com": {
        "quadrant": "C",
        "label": "Dot & Key",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 120,
            "median_price": 445,
            "p90_price": 1148,
            "premium_share": 0,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "discoverpilgrim.com": {
        "quadrant": "C",
        "label": "Pilgrim",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 101,
            "median_price": 595,
            "p90_price": 1150,
            "premium_share": 0,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "www.mcaffeine.com": {
        "quadrant": "C",
        "label": "mCaffeine",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 120,
            "median_price": 499,
            "p90_price": 899,
            "premium_share": 0,
            "discount_rate": 1,
            "median_discount": 34,
            "p80_discount": 0
        }
    },
    "in.sugarcosmetics.com": {
        "quadrant": "C",
        "label": "SUGAR",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 120,
            "median_price": 551,
            "p90_price": 1299,
            "premium_share": 3,
            "discount_rate": 47,
            "median_discount": 15,
            "p80_discount": 15
        }
    },
    "mamaearth.in": {
        "quadrant": "C",
        "label": "Mamaearth",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 120,
            "median_price": 524,
            "p90_price": 898,
            "premium_share": 0,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "plumgoodness.com": {
        "quadrant": "C",
        "label": "Plum",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 120,
            "median_price": 468,
            "p90_price": 1067,
            "premium_share": 0,
            "discount_rate": 86,
            "median_discount": 15,
            "p80_discount": 19
        }
    },
    "bellavitaorganic.com": {
        "quadrant": "C",
        "label": "Bella Vita",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 113,
            "median_price": 449,
            "p90_price": 799,
            "premium_share": 0,
            "discount_rate": 89,
            "median_discount": 39,
            "p80_discount": 50
        }
    },
    "beardo.in": {
        "quadrant": "C",
        "label": "Beardo",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 119,
            "median_price": 599,
            "p90_price": 999,
            "premium_share": 0,
            "discount_rate": 90,
            "median_discount": 41,
            "p80_discount": 54
        }
    },
    "themancompany.com": {
        "quadrant": "C",
        "label": "The Man Company",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 119,
            "median_price": 349,
            "p90_price": 1077,
            "premium_share": 3,
            "discount_rate": 63,
            "median_discount": 23,
            "p80_discount": 40
        }
    },
    "bombayshavingcompany.com": {
        "quadrant": "C",
        "label": "Bombay Shaving",
        "category": "beauty",
        "queries": [
            "serum",
            "cream",
            "face wash",
            "perfume"
        ],
        "measured": {
            "n": 115,
            "median_price": 379,
            "p90_price": 1099,
            "premium_share": 3,
            "discount_rate": 12,
            "median_discount": 42,
            "p80_discount": 0
        }
    },
    "www.boat-lifestyle.com": {
        "quadrant": "C",
        "label": "boAt",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 90,
            "median_price": 1699,
            "p90_price": 6499,
            "premium_share": 31,
            "discount_rate": 99,
            "median_discount": 69,
            "p80_discount": 77
        }
    },
    "www.gonoise.com": {
        "quadrant": "C",
        "label": "Noise",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 70,
            "median_price": 1949,
            "p90_price": 4999,
            "premium_share": 37,
            "discount_rate": 89,
            "median_discount": 60,
            "p80_discount": 69
        }
    },
    "zebronics.com": {
        "quadrant": "C",
        "label": "Zebronics",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 90,
            "median_price": 6449,
            "p90_price": 34999,
            "premium_share": 80,
            "discount_rate": 0,
            "median_discount": 0,
            "p80_discount": 0
        }
    },
    "mivi.in": {
        "quadrant": "C",
        "label": "Mivi",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 60,
            "median_price": 1999,
            "p90_price": 11999,
            "premium_share": 42,
            "discount_rate": 95,
            "median_discount": 74,
            "p80_discount": 79
        }
    },
    "boultaudio.com": {
        "quadrant": "C",
        "label": "Boult",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 65,
            "median_price": 1499,
            "p90_price": 2999,
            "premium_share": 20,
            "discount_rate": 97,
            "median_discount": 71,
            "p80_discount": 79
        }
    },
    "portronics.com": {
        "quadrant": "C",
        "label": "Portronics",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 86,
            "median_price": 1512,
            "p90_price": 6999,
            "premium_share": 21,
            "discount_rate": 100,
            "median_discount": 48,
            "p80_discount": 57
        }
    },
    "www.ambraneindia.com": {
        "quadrant": "C",
        "label": "Ambrane",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 68,
            "median_price": 1749,
            "p90_price": 2499,
            "premium_share": 9,
            "discount_rate": 96,
            "median_discount": 42,
            "p80_discount": 50
        }
    },
    "ptron.in": {
        "quadrant": "C",
        "label": "pTron",
        "category": "electronics",
        "queries": [
            "earbuds",
            "smartwatch",
            "speaker"
        ],
        "measured": {
            "n": 90,
            "median_price": 2134,
            "p90_price": 3799,
            "premium_share": 37,
            "discount_rate": 50,
            "median_discount": 49,
            "p80_discount": 51
        }
    },
    "www.redtape.com": {
        "quadrant": "C",
        "label": "Red Tape",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 89,
            "median_price": 1071,
            "p90_price": 1392,
            "premium_share": 0,
            "discount_rate": 100,
            "median_discount": 84,
            "p80_discount": 85
        }
    },
    "campusshoes.com": {
        "quadrant": "C",
        "label": "Campus",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 88,
            "median_price": 1084,
            "p90_price": 1619,
            "premium_share": 0,
            "discount_rate": 89,
            "median_discount": 44,
            "p80_discount": 56
        }
    },
    "baccabucci.com": {
        "quadrant": "C",
        "label": "Bacca Bucci",
        "category": "footwear",
        "queries": [
            "sneakers",
            "shoes",
            "sandals"
        ],
        "measured": {
            "n": 88,
            "median_price": 1249,
            "p90_price": 2399,
            "premium_share": 7,
            "discount_rate": 100,
            "median_discount": 57,
            "p80_discount": 68
        }
    },
    "wrogn.com": {
        "quadrant": "C",
        "label": "WROGN",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 119,
            "median_price": 1599,
            "p90_price": 2649,
            "premium_share": 14,
            "discount_rate": 100,
            "median_discount": 38,
            "p80_discount": 43
        }
    },
    "libas.in": {
        "quadrant": "C",
        "label": "Libas",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "saree"
        ],
        "measured": {
            "n": 115,
            "median_price": 819,
            "p90_price": 2429,
            "premium_share": 9,
            "discount_rate": 100,
            "median_discount": 61,
            "p80_discount": 70
        }
    },
    "nobero.com": {
        "quadrant": "C",
        "label": "Nobero",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 116,
            "median_price": 999,
            "p90_price": 1999,
            "premium_share": 9,
            "discount_rate": 100,
            "median_discount": 25,
            "p80_discount": 30
        }
    },
    "xyxxcrew.com": {
        "quadrant": "C",
        "label": "XYXX",
        "category": "menswear",
        "queries": [
            "shirt",
            "t-shirt",
            "jacket",
            "trouser"
        ],
        "measured": {
            "n": 119,
            "median_price": 999,
            "p90_price": 1999,
            "premium_share": 6,
            "discount_rate": 87,
            "median_discount": 23,
            "p80_discount": 27
        }
    },
    "palmonas.com": {
        "quadrant": "C",
        "label": "PALMONAS",
        "category": "jewellery",
        "queries": [
            "necklace",
            "earrings",
            "ring",
            "bracelet"
        ],
        "measured": {
            "n": 120,
            "median_price": 1055,
            "p90_price": 2875,
            "premium_share": 17,
            "discount_rate": 99,
            "median_discount": 65,
            "p80_discount": 69
        }
    },
    "eyewearlabs.com": {
        "quadrant": "C",
        "label": "Eyewear Labs",
        "category": "eyewear",
        "queries": [
            "sunglasses",
            "eyeglasses"
        ],
        "measured": {
            "n": 59,
            "median_price": 1499,
            "p90_price": 2599,
            "premium_share": 14,
            "discount_rate": 100,
            "median_discount": 64,
            "p80_discount": 72
        }
    },
    "supertails.com": {
        "quadrant": "C",
        "label": "Supertails",
        "category": "pets",
        "queries": [
            "dog food",
            "treat",
            "toy"
        ],
        "measured": {
            "n": 89,
            "median_price": 545,
            "p90_price": 2138,
            "premium_share": 6,
            "discount_rate": 98,
            "median_discount": 12,
            "p80_discount": 19
        }
    },
    "virgio.com": {
        "quadrant": "C",
        "label": "Virgio",
        "category": "womenswear",
        "queries": [
            "dress",
            "kurta",
            "top",
            "co-ord"
        ],
        "measured": {
            "n": 151,
            "median_price": 1099,
            "p90_price": 2199,
            "premium_share": 8,
            "discount_rate": 100,
            "median_discount": 43,
            "p80_discount": 57
        }
    }
}

BY_QUADRANT = {q: [d for d, r in ROSTER.items() if r["quadrant"] == q]
               for q in ("A", "B", "C")}
BRANDS = {d: (d, r["queries"]) for d, r in ROSTER.items()}
BRAND_LABEL = {d: r["label"] for d, r in ROSTER.items()}
QUADRANT = {d: r["quadrant"] for d, r in ROSTER.items()}
