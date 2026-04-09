from typing import Any

def calculate_bank_value(rating: float) -> int:
    """
    Formula: 10000 * (rating / 2200)^4
    """
    return int(10000 * (rating / 2200)**3)

def calculate_yield_value(bank_value: int) -> int:
    """
    Formula: bank_value / 10
    """
    return int(bank_value / 10)

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
        "X": 0.9,
        "S": 0.8,
        "A": 0.7,
        "B": 0.6,
        "C": 0.5,
        "D": 0.4
    }
    
    return int(bank * multipliers.get(rarity, 0.4))

def calculate_min_increment(bank_value: int) -> int:
    """
    Increment is 5% of Bank Value.
    """
    return int(bank_value * 0.05)
