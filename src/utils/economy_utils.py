from typing import Any, Optional

WEALTH_ROLES_NAMED = [
    (0,        "Aficionado"),
    (1_000,    "Amateur"),
    (2_000,    "Grand Amateur"),
    (4_000,    "Collector"),
    (8_000,    "Grand Collector"),
    (16_000,   "Appraiser"),
    (32_000,   "Grand Appraiser"),
    (64_000,   "Gourmand"),
    (128_000,  "Grand Gourmand"),
    (256_000,  "Sommelier"),
    (512_000,  "Grand Sommelier"),
    (1_024_000, "Connoisseur"),
    (2_048_000, "Grand Connoisseur"),
]


def esc(name: str) -> str:
    return name.replace("_", "\\_")


def get_rank_bar(combined: float, bar_width: int = 10) -> str:
    combined = int(combined)
    idx = 0
    for i, (threshold, _) in enumerate(WEALTH_ROLES_NAMED):
        if combined >= threshold:
            idx = i
    lower = WEALTH_ROLES_NAMED[idx][0]
    if idx >= len(WEALTH_ROLES_NAMED) - 1:
        return f"[{'#' * bar_width}] MAX"
    upper = WEALTH_ROLES_NAMED[idx + 1][0]
    next_name = WEALTH_ROLES_NAMED[idx + 1][1]
    progress = (combined - lower) / (upper - lower)
    filled = int(progress * bar_width)
    bar = "#" * filled + " · " * (bar_width - filled)
    return f"[{bar}] to {next_name}"

# Tiered daily dividend rate per rarity. Keep in sync with the CASE expressions
# in src/database.py (process_faucet_dividends, get_economy_stats).
YIELD_RATES = {
    "X": 0.30,
    "SS": 0.26,
    "S": 0.22,
    "A": 0.18,
    "B": 0.14,
    "C": 0.14,
    "D": 0.14,
}


def calculate_bank_value(rating: float) -> int:
    """
    Formula: 10000 * (rating / 2200)^4
    """
    return int(10000 * (rating / 2200) ** 3)


def calculate_yield_value(bank_value: int, rank: Any) -> int:
    return int(bank_value * YIELD_RATES[get_rarity(rank)])


def get_rarity(rank: Any) -> str:
    """Determine rarity based on rank threshold."""
    if rank == "N/A" or rank is None:
        return "D"
    rank = int(rank)
    if rank <= 10:
        return "X"
    if rank <= 50:
        return "SS"
    if rank <= 100:
        return "S"
    if rank <= 250:
        return "A"
    if rank <= 500:
        return "B"
    if rank <= 1000:
        return "C"
    return "D"


def calculate_min_bid(rating: float, rank: Any) -> int:
    """
    Min Bid is a percentage of bank value based on tier.
    """
    bank = calculate_bank_value(rating)
    rarity = get_rarity(rank)

    multipliers = {
        "X": 1.0,
        "SS": 0.95,
        "S": 0.90,
        "A": 0.80,
        "B": 0.70,
        "C": 0.60,
        "D": 0.50,
    }

    return int(bank * multipliers.get(rarity, 0.4))


def calculate_min_increment(bank_value: int) -> int:
    """
    Increment is 5% of Bank Value.
    """
    return max(1, int(bank_value * 0.05))


HOLD_HOURS = 8


def sell_hold_remaining(acquired_at) -> Optional[str]:
    """Returns 'H:MM' string if still in the hold window, None if sellable."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    hold_until = acquired_at.replace(tzinfo=timezone.utc) + timedelta(hours=HOLD_HOURS)
    if now >= hold_until:
        return None
    remaining = hold_until - now
    total_minutes = int(remaining.total_seconds()) // 60
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"
