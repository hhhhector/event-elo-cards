from typing import Any

def calculate_bank_value(rating: float) -> int:
    """
    Formula: 10000 * (rating / 2200)^4
    """
    return int(10000 * (rating / 2200)**3)

def calculate_yield_value(bank_value: int) -> int:
    return int(bank_value / 7)

def get_rarity(rank: Any) -> str:
    """Determine rarity based on rank threshold."""
    if rank == "N/A" or rank is None:
        return "D"
    rank = int(rank)
    if rank <= 10:
        return "X"
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
        "X": 0.95,
        "S": 0.90,
        "A": 0.80,
        "B": 0.70,
        "C": 0.60,
        "D": 0.50
    }
    
    return int(bank * multipliers.get(rarity, 0.4))

def calculate_min_increment(bank_value: int) -> int:
    """
    Increment is 5% of Bank Value.
    """
    return max(1, int(bank_value * 0.05))
