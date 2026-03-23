import io
import urllib.parse
from typing import Any, Dict

import aiohttp

from src.utils.economy_utils import calculate_bank_value, calculate_yield_value, get_rarity

API_BASE_URL = "https://event-elo-satori.vercel.app/api/generate-card"


async def generate_card_image(stats: Dict[str, Any]) -> io.BytesIO:
    """
    Fetches the card image from the Vercel Satori API.
    """
    raw_rating = stats.get("current_drating")
    if raw_rating is None:
        raise ValueError("Missing 'current_drating' in player statistics.")
    
    float_rating = float(raw_rating)
    rating = int(float_rating)
    rank = stats.get("current_rank", "N/A")
    peak_rating = stats.get("peak_rating", "N/A")
    peak_rank = stats.get("peak_rank", "N/A")

    if peak_rating != "N/A":
        peak_rating = int(float(peak_rating))
    if rank != "N/A":
        rank = int(rank)
    if peak_rank != "N/A":
        peak_rank = int(peak_rank)

    bank_value = calculate_bank_value(float_rating)
    yield_value = calculate_yield_value(bank_value)

    # Map database stats to API parameters
    params = {
        "name": stats.get("current_name", "Unknown"),
        "rating": rating,
        "rank": rank,
        "peak_rating": peak_rating,
        "peak_rank": peak_rank,
        "bank": bank_value,
        "yield": yield_value,
        "rarity": get_rarity(rank) if rank != "N/A" else "D",
    }

    # URL encoded parameters
    query_string = urllib.parse.urlencode(params)
    api_url = f"{API_BASE_URL}?{query_string}"

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Satori API Error ({resp.status}): {error_text}")

            data = await resp.read()
            return io.BytesIO(data)

async def create_card_grid(image_buffers: list[io.BytesIO], cols: int = 3) -> io.BytesIO:
    """
    Stitches multiple card images together into a grid (default 3 columns).
    """
    from PIL import Image
    import math

    images = [Image.open(buffer) for buffer in image_buffers]
    if not images:
        return io.BytesIO()

    card_w = images[0].width
    card_h = images[0].height
    
    rows = math.ceil(len(images) / cols)
    
    grid_w = cols * card_w
    grid_h = rows * card_h
    
    combined = Image.new("RGBA", (grid_w, grid_h))
    
    for index, img in enumerate(images):
        x = (index % cols) * card_w
        y = (index // cols) * card_h
        combined.paste(img, (x, y))
    
    out_buffer = io.BytesIO()
    combined.save(out_buffer, format="PNG")
    out_buffer.seek(0)
    return out_buffer
