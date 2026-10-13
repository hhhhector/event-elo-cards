"""
Hiding users who are no longer in the Discord server.

Accounts are deliberately never deleted when someone is banned from the server,
so that unbanning them restores everything. Instead they're filtered out at
display time, anywhere the bot would otherwise surface another user's identity.

"Hidden" means not currently a guild member, which covers both bans and people
who simply left. A mention for someone who left renders as a dead `<@id>`
anyway, and the filter self-heals if they rejoin.

Commands taking a `discord.Member` parameter (/inv, /trade, /sell, /buy) are
already gated by Discord itself, which only resolves members of the guild.
"""

from typing import Any, Callable, Iterable, Optional, Sequence

import discord


def _cache_is_usable(guild: discord.Guild) -> bool:
    """
    True if the member cache looks populated enough to filter against.

    `intents.members` is on and discord.py chunks guilds at startup, so this is
    normally true. But if chunking failed we would otherwise hide *everyone*,
    blanking the leaderboard. Failing open shows a banned user for one 10-minute
    stats cycle, which is a much better failure than an empty board.
    """
    expected = guild.member_count or 0
    cached = len(guild.members)
    if expected and cached < min(expected * 0.5, expected - 1):
        print(
            f"⚠️ Member cache looks cold ({cached}/{expected}); "
            "skipping the not-in-server filter this pass."
        )
        return False
    return cached > 0


def is_visible(guild: Optional[discord.Guild], discord_id: Any) -> bool:
    """True if this user should be shown. Unknown guild -> show (fail open)."""
    if guild is None:
        return True
    try:
        uid = int(discord_id)
    except (TypeError, ValueError):
        return False
    return guild.get_member(uid) is not None


def filter_visible(
    guild: Optional[discord.Guild],
    rows: Sequence[Any],
    key: Callable[[Any], Any],
    limit: Optional[int] = None,
) -> list:
    """
    Drop rows whose user is no longer in the guild, then take the first `limit`.

    Callers that need N visible rows should over-fetch from the database and
    pass `limit=N`, otherwise a top-10 silently shrinks to a top-7 whenever
    three of them have left.
    """
    if guild is None or not _cache_is_usable(guild):
        return list(rows)[:limit] if limit else list(rows)
    kept = [r for r in rows if is_visible(guild, key(r))]
    return kept[:limit] if limit else kept
