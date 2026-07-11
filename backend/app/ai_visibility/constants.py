"""Seed configuration for the Best&Less AI-visibility pilot.

Sourced from ``AEO_Business_Proposal_BestAndLess.md`` §19 (project config) and
Appendix D (the standing 25-prompt unaided panel). Used to prefill the setup
form and (optionally) a seed script so the benchmark can be launched with no
manual data entry.
"""

from __future__ import annotations

BEST_AND_LESS_PROJECT: dict = {
    "name": "Best&Less Australia — AI Visibility Pilot",
    "brand_name": "Best&Less",
    "brand_aliases": ["Best&Less", "Best & Less", "Best and Less"],
    "owned_domains": ["bestandless.com.au"],
    "unintended_domains": [
        "bestlesscomau.zendesk.com",
        "jsapps.co6tqo-bestlesss1-p1-public.model-t.cc.commerce.ondemand.com",
    ],
    "competitors": [
        {
            "name": "Kmart",
            "aliases": ["Kmart", "Kmart Australia"],
            "domains": ["kmart.com.au"],
        },
        {
            "name": "Target",
            "aliases": ["Target", "Target Australia"],
            "domains": ["target.com.au"],
        },
        {
            "name": "BIG W",
            "aliases": ["BIG W", "Big W", "BigW"],
            "domains": ["bigw.com.au"],
        },
    ],
    "country_code": "AU",
    "language_code": "en-AU",
    "benchmark_mode": "controlled_localized",
    "default_repetitions": 3,
}

# (prompt_text, theme, intent) — Appendix D order preserved.
BEST_AND_LESS_PROMPTS: list[dict] = [
    {
        "text": "cheapest place to buy school uniforms in Australia",
        "theme": "Schoolwear",
        "intent": "discovery",
    },
    {
        "text": "best value school polo shirts Australia",
        "theme": "Schoolwear",
        "intent": "discovery",
    },
    {
        "text": "where to buy plain school shorts and pants online Australia",
        "theme": "Schoolwear",
        "intent": "discovery",
    },
    {
        "text": "affordable kids winter clothes Australia",
        "theme": "Kidswear",
        "intent": "discovery",
    },
    {
        "text": "cheap kids t-shirt multipacks Australia",
        "theme": "Kidswear",
        "intent": "discovery",
    },
    {
        "text": "best value kids tracksuits Australia",
        "theme": "Kidswear",
        "intent": "discovery",
    },
    {
        "text": "where to buy Bluey clothes for kids Australia",
        "theme": "Licensed character",
        "intent": "discovery",
    },
    {
        "text": "kids licensed character pyjamas Australia",
        "theme": "Licensed character",
        "intent": "discovery",
    },
    {
        "text": "affordable toddler clothes Australia",
        "theme": "Toddler",
        "intent": "discovery",
    },
    {
        "text": "cheap toddler winter jackets Australia",
        "theme": "Toddler",
        "intent": "discovery",
    },
    {
        "text": "best value baby bodysuit multipacks Australia",
        "theme": "Baby",
        "intent": "discovery",
    },
    {
        "text": "cheap baby winter clothes Australia",
        "theme": "Baby",
        "intent": "discovery",
    },
    {
        "text": "affordable newborn essentials clothing Australia",
        "theme": "Baby",
        "intent": "discovery",
    },
    {
        "text": "cheap women's pyjamas Australia",
        "theme": "Womenswear",
        "intent": "discovery",
    },
    {
        "text": "affordable women's basics Australia",
        "theme": "Womenswear",
        "intent": "discovery",
    },
    {
        "text": "best value women's underwear multipacks Australia",
        "theme": "Womenswear",
        "intent": "discovery",
    },
    {
        "text": "affordable plus size clothing Australia",
        "theme": "Plus-size",
        "intent": "discovery",
    },
    {
        "text": "budget men's underwear multipacks Australia",
        "theme": "Menswear",
        "intent": "discovery",
    },
    {
        "text": "cheap men's flannelette shirts Australia",
        "theme": "Menswear",
        "intent": "discovery",
    },
    {
        "text": "men's socks multipack under $10 Australia",
        "theme": "Menswear",
        "intent": "purchase",
    },
    {
        "text": "cheap NRL supporter gear Australia",
        "theme": "Licensed sports",
        "intent": "discovery",
    },
    {
        "text": "best budget family clothing store Australia",
        "theme": "Family value",
        "intent": "discovery",
    },
    {
        "text": "alternatives to Kmart for cheap kids clothes Australia",
        "theme": "Competitor alternative",
        "intent": "comparison",
    },
    {
        "text": "which clothing stores offer click and collect in Australia",
        "theme": "Service",
        "intent": "service",
    },
    {
        "text": "cheap school uniforms in Sydney Australia",
        "theme": "Schoolwear / local",
        "intent": "local",
    },
]

# The 5-prompt pre-Monday validation subset (proposal §19).
BEST_AND_LESS_SUBSET_INDICES: tuple[int, ...] = (0, 6, 10, 14, 17)
