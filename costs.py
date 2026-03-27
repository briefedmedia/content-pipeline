# costs.py -- pipeline cost tracking
# All prices are confirmed from official sources or fetched live.
# Hardcoded fallbacks only where APIs don't expose pricing endpoints.

import datetime, os, time, requests
from dotenv import load_dotenv
load_dotenv()

# ── Confirmed static prices ───────────────────────────────────────────────────
# Source: platform.claude.com/docs/en/about-claude/pricing — verified March 2026

CLAUDE_OPUS_INPUT_PER_MTK    = 5.00    # per 1M input tokens, claude-opus-4-x
CLAUDE_OPUS_OUTPUT_PER_MTK   = 25.00   # per 1M output tokens
CLAUDE_SONNET_INPUT_PER_MTK  = 3.00    # per 1M input tokens, claude-sonnet-4-x
CLAUDE_SONNET_OUTPUT_PER_MTK = 15.00   # per 1M output tokens

# Source: platform.openai.com/docs/pricing — verified March 2026
DALLE3_HD_PER_IMAGE          = 0.080   # 1024x1792 or 1024x1024 HD quality
DALLE3_STD_PER_IMAGE         = 0.040   # 1024x1024 standard quality

# Source: cloud.google.com/text-to-speech/pricing — verified March 2026
GOOGLE_TTS_NEURAL2_PER_MCHAR = 16.00   # per 1M characters, Neural2 voices
GOOGLE_TTS_FREE_MONTHLY_CHARS = 1_000_000  # 1M free chars/month for Neural2

# User-configurable
MONTHLY_BUDGET               = 300.00

# Confirmed subscriptions — update if plans change
FIXED_MONTHLY_COSTS = {
    "Claude Max":       100.00,   # claude.ai subscription, NOT API usage
    "Railway Pro":       20.00,   # railway.com Pro plan
    "Google Workspace":  12.00,   # 1 user Business Standard
}
FIXED_MONTHLY_TOTAL = sum(FIXED_MONTHLY_COSTS.values())

# ── FAL pricing cache ─────────────────────────────────────────────────────────

_fal_cache      = {}
_fal_cache_time = 0
_FAL_CACHE_TTL  = 3600  # 1 hour

def fetch_fal_pricing():
    """Fetch live FAL.ai model pricing. Caches in memory for 1 hour.

    Returns dict of endpoint_id -> price_per_second (or per_unit).
    Falls back to hardcoded estimates on failure.
    """
    global _fal_cache, _fal_cache_time
    now = time.time()
    if _fal_cache and (now - _fal_cache_time) < _FAL_CACHE_TTL:
        return _fal_cache

    fal_key = os.getenv("FAL_KEY", "")
    try:
        r = requests.get(
            "https://fal.ai/api/v1/models/pricing",
            headers={"Authorization": f"Key {fal_key}"},
            timeout=10,
        )
        r.raise_for_status()
        data        = r.json()
        _fal_cache  = data if isinstance(data, dict) else {}
        _fal_cache_time = now
        return _fal_cache
    except Exception as e:
        print(f"  [costs] FAL pricing fetch failed: {e} -- using fallbacks")
        # Return hardcoded fallbacks (not cached so we retry next call)
        return {
            "fal-ai/pika/v2.2/image-to-video": 0.07,  # estimated $/second
            "fal-ai/kling-video/v2.5/turbo/image-to-video": 0.07,
        }


def get_fal_price(endpoint_id):
    """Return price per second for a FAL endpoint. Fallback: $0.07/s."""
    prices = fetch_fal_pricing()
    return prices.get(endpoint_id, 0.07)


# ── Cost calculation functions ────────────────────────────────────────────────

def calc_claude_cost(model, input_tokens, output_tokens):
    if "opus" in model.lower():
        return ((input_tokens  * CLAUDE_OPUS_INPUT_PER_MTK) +
                (output_tokens * CLAUDE_OPUS_OUTPUT_PER_MTK)) / 1_000_000
    return ((input_tokens  * CLAUDE_SONNET_INPUT_PER_MTK) +
            (output_tokens * CLAUDE_SONNET_OUTPUT_PER_MTK)) / 1_000_000


def calc_dalle_cost(num_images, quality="hd"):
    rate = DALLE3_HD_PER_IMAGE if quality == "hd" else DALLE3_STD_PER_IMAGE
    return num_images * rate


def calc_fal_cost(endpoint_id, seconds_generated):
    price = get_fal_price(endpoint_id)
    return seconds_generated * price


def calc_tts_cost(char_count, monthly_chars_used_so_far=0):
    billable = max(0, char_count - max(0,
        GOOGLE_TTS_FREE_MONTHLY_CHARS - monthly_chars_used_so_far))
    return (billable * GOOGLE_TTS_NEURAL2_PER_MCHAR) / 1_000_000


def get_fixed_costs():
    return {"items": FIXED_MONTHLY_COSTS, "total": FIXED_MONTHLY_TOTAL}


# ── CostTracker ───────────────────────────────────────────────────────────────

class CostTracker:
    def __init__(self, slug, account_type):
        self.slug         = slug
        self.account_type = account_type
        self.date         = slug[:10] if slug else ""
        self.entries      = []
        self.total        = 0.0

    def add(self, service, description, units, unit_cost, total_cost):
        entry = {
            "service":     service,
            "description": description,
            "units":       str(units),
            "unit_cost":   unit_cost,
            "total":       round(total_cost, 6),
            "timestamp":   datetime.datetime.now().isoformat(),
        }
        self.entries.append(entry)
        self.total += total_cost
        return total_cost

    def add_claude(self, call_name, model, input_tokens, output_tokens):
        cost = calc_claude_cost(model, input_tokens, output_tokens)
        tier = "Opus" if "opus" in model.lower() else "Sonnet"
        return self.add(
            f"Claude {tier}", call_name,
            f"{input_tokens}in + {output_tokens}out tokens",
            None, cost
        )

    def add_dalle(self, num_images, quality="hd"):
        cost = calc_dalle_cost(num_images, quality)
        rate = DALLE3_HD_PER_IMAGE if quality == "hd" else DALLE3_STD_PER_IMAGE
        return self.add(
            "DALL-E 3",
            f"{num_images}x {quality.upper()} images",
            num_images, rate, cost
        )

    def add_fal(self, scene_index, endpoint_id, seconds_generated):
        cost  = calc_fal_cost(endpoint_id, seconds_generated)
        price = get_fal_price(endpoint_id)
        return self.add(
            "FAL.ai",
            f"Scene {scene_index + 1} clip ({seconds_generated:.1f}s)",
            f"{seconds_generated:.1f}s", price, cost
        )

    def add_tts(self, char_count, monthly_chars_used=0):
        cost = calc_tts_cost(char_count, monthly_chars_used)
        return self.add(
            "Google TTS",
            f"{char_count:,} characters Neural2",
            char_count, GOOGLE_TTS_NEURAL2_PER_MCHAR, cost
        )

    def summary(self):
        by_service = {}
        for e in self.entries:
            s = e["service"]
            by_service[s] = round(by_service.get(s, 0) + e["total"], 6)
        return {
            "slug":         self.slug,
            "date":         self.date,
            "account_type": self.account_type,
            "total":        round(self.total, 4),
            "by_service":   by_service,
            "entries":      self.entries,
        }
