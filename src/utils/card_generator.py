import io
import aiohttp
from PIL import Image, ImageDraw, ImageFont

async def generate_card_image(player_name: str, drating: int, uuid: str = None) -> io.BytesIO:
    """
    Generates a card image dynamically. Uses a black canvas with a gold border,
    fetches the Minecraft avatar, and overlays text.
    """
    base_img = Image.new("RGBA", (300, 450), (40, 40, 40, 255))
    draw = ImageDraw.Draw(base_img)
    
    # Gold border
    draw.rectangle([(10, 10), (290, 440)], outline=(218, 165, 32, 255), width=5)

    # Fetch Avatar from Minotar
    avatar_url = f"https://minotar.net/armor/bust/{player_name}/200.png"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()
                    avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                    # Paste avatar in center
                    base_img.paste(avatar_img, (50, 50), avatar_img)
    except Exception as e:
        print(f"Failed to fetch avatar for {player_name}: {e}")
        # Placeholder square if fetch fails
        draw.rectangle([(50, 50), (250, 250)], fill=(100, 100, 100, 255))

    # Add Text (Name & Rating)
    try:
        # Standard system fonts might not be available, fallback to default if so
        font_large = ImageFont.truetype("arial.ttf", 36)
        font_small = ImageFont.truetype("arial.ttf", 24)
    except IOError:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # PIL doesn't have an exact anchor without bbox checking in older versions, 
    # but modern PIL supports it. We use a simple manual offset.
    text_bbox_large = draw.textbbox((0, 0), player_name, font=font_large)
    text_w_large = text_bbox_large[2] - text_bbox_large[0]
    draw.text(((300 - text_w_large) / 2, 280), player_name, font=font_large, fill=(255, 255, 255, 255))

    rating_text = f"Rating: {drating}"
    text_bbox_small = draw.textbbox((0, 0), rating_text, font=font_small)
    text_w_small = text_bbox_small[2] - text_bbox_small[0]
    draw.text(((300 - text_w_small) / 2, 330), rating_text, font=font_small, fill=(255, 215, 0, 255))

    buffer = io.BytesIO()
    base_img.save(buffer, format="PNG")
    buffer.seek(0)
    
    return buffer
