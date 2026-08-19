# **Single Source of Truth (SSOT): Esports Trading Card Economy**

Every number here is mirrored in code. The authoritative locations are noted per section. If you change a value, change it in both places.

## **1. The Core Valuation Math**

*Code: `src/utils/economy_utils.py`*

* **Market Value is Bank Value:** No exit taxes or hidden fees. If the bank value is 5,000, selling to the bank yields exactly 5,000.
* **The Anchor Formula:** `Bank Value = 10000 * (drating / 2200)^3`. X-Tier cards are legendary; D-Tier cards are extremely cheap. Note this runs on **drating** (`rating - 2*RD`), not raw rating.
* **Rarity Tiers** are by current global rank: X ≤ 10, SS ≤ 50, S ≤ 100, A ≤ 250, B ≤ 500, C ≤ 1000, D beyond that (and for unranked).
* **Daily Dividends:** Yield is a percentage of Bank Value, tiered by rarity:

  | Tier | Yield | ROI |
  |---|---|---|
  | X  | 30% | ~3.3 days |
  | SS | 26% | ~3.8 days |
  | S  | 22% | ~4.5 days |
  | A  | 18% | ~5.6 days |
  | B / C / D | 14% | ~7.1 days |

  Top-tier cards pay back faster, which is what makes them worth fighting over rather than just expensive. Paid once daily at **12:00 UTC**, not on a rolling 24h timer. Archived cards yield nothing.

## **2. Drop Mechanics**

*Code: `src/cogs/auction.py`*

* **The Heartbeat (Railway-Proof):** A 1-minute `discord.ext.tasks` loop checks `discord_tcg.system_state.next_drop_timestamp`. This prevents timer amnesia on server restarts. A timestamp more than a minute stale (maintenance window) reschedules instead of firing, so the bot never dumps a backlog of drops on wake.
* **The Timing (Exponential, time-of-day weighted):** Mean gap varies by UTC hour to track when people are actually around:

  | UTC hour | Mean gap |
  |---|---|
  | 20:00–23:59 | 5 min |
  | 16:00–19:59 | 8 min |
  | 00:00–03:59 | 8 min |
  | 04:00–05:59 | 10 min |
  | 12:00–15:59 | 12 min |
  | 06:00–11:59 | 15 min |

  Drawn from an exponential distribution and clamped to `[mean/4, mean*2]`. Players never know exactly when the next drop hits, forcing them to hold liquid cash.
* **The Supply:** A flat **8 cards per drop**, sampled uniformly at random from unbanned players with a rating. Not Poisson-distributed.
* **Auction Length:** Randomized **7 to 15 minutes** per drop.
* **Auction Overlap:** None. `system_state.is_active` gates the drop loop, so a drop can't fire while one is live.
* **Infinite Generations:** No global hard limits on card copies. Multiple players can own the same player.
* **Misprints:** 1% roll per card per drop for a left-facing variant. **Only one misprint can ever exist per player** — the roll checks active and archived cards before granting. Toggle with `MISPRINTS_ENABLED` in `auction.py`.
* **Notifications:** Drops ping the auction role, plus any user who has that specific player wishlisted.

## **3. Bidding Rules & UI**

*Code: `src/cogs/auction.py`, `src/utils/economy_utils.py`*

* **The "Pick One" Rule:** A player can only hold the **highest bid** on one card per drop. They may bid elsewhere after being outbid. This forces whales to fight each other over S-Tiers, leaving the D-Tiers uncontested for beginners.
* **The Dynamic Spread (Anti-Exploit):** Starting bid as a fraction of Bank Value:

  | Tier | Min bid |
  |---|---|
  | X  | 100% |
  | SS | 95% |
  | S  | 90% |
  | A  | 80% |
  | B  | 70% |
  | C  | 60% |
  | D  | 50% |

  D-Tiers carry real arbitrage; X-Tiers have none, so they must be held for yield.
* **Bidding Interface:** Bids are submitted via a Discord text Modal rather than clicking buttons. This completely prevents 1-coin penny wars.
* **Minimum Increment:** 5% of Bank Value for all tiers. Allows rich players to instabid large amounts while keeping penny wars impossible.
* **Fat-Finger Guard:** Any bid above 5x the current minimum next bid pops a confirmation view before it lands.
* **Escrow:** Coins are deducted on bid and refunded atomically when outbid.
* **Currency Symbol:** ⛃ placed before the number (e.g., ⛃ 3,233).

## **4. Player Inventory & Progression**

*Code: `src/cogs/economy.py`, `src/cogs/inventory.py`*

* **The Starter Pack:** `/register` injects **⛃ 1,000** for a new player to win an uncontested D-Tier and enter the arbitrage hustle.
* **The Roster Cap:** Base **10 cards**, expandable to **20** via `/upgradeinventory`. All active cards generate yield, so the cap is what stops infinite compounding. To exceed it a player must liquidate or archive. Duplicates of the same card are fully allowed.
* **Roster Check at Bid Time:** If a player's roster is full, their bid is rejected immediately with a message to sell a card first.
* **The 8-Hour Hold:** Cards can't be sold to the bank until 8 hours after acquisition. This is what stops instant buy-low-sell-high flipping inside a single drop from being risk-free.
* **Archiving:** `/archive` permanently retires a card from the active roster. Zero yield, can't be sold or traded, doesn't count toward the cap. It's the collector's option, and it's one-way (`/burn` deletes archived cards outright).
* **The Progression Loop:**
  * *Early Game:* Buy cheap D-tiers, hold 8 hours, sell to Bank for the arbitrage spread.
  * *Mid Game:* Roster gets full. Stop flipping, start saving dividends to upgrade slots to A-Tiers.
  * *Late Game:* Yieldmaxxing. Spending massive wealth outbidding other whales for God-tier cards.

## **5. Wealth Sinks (Inflation Control)**

*Code: `ROSTER_UPGRADE_PRICES` in `src/utils/economy_utils.py`*

* **Roster Expansions:** Ten purchasable slots on an exponential curve: 10k, 25k, 50k, 100k, 250k, 500k, 1M, 2.5M, 5M, 10M. Total cost to reach 20 slots is ⛃ 19,435,000.
* **Wealth Roles:** 13 cosmetic Discord roles from Aficionado (0) to Grand Connoisseur (2,048,000), assigned on combined coins + portfolio value. Not a sink, but the visible prestige ladder the sinks feed.

### Designed but not implemented

Both of these are in the design but have no code. Don't assume they exist.

* **Cosmetic Flexes:** Upgrading a card to "Holographic" for 3x its Bank Value. Changes nothing about stats, just makes the embed glow.
* **Sponsored Drops:** Whales pay ⛃ 15,000 to force a public drop off-schedule with a banner naming them. (No VIP fast-passes or gacha mechanics; they'd still bid like everyone else.)

## **6. Peer-to-Peer Market**

*Code: `src/cogs/market.py`, `src/cogs/trade.py`*

Added after the original design. All three flows are offer-then-confirm: one side proposes, the other runs the mirrored command to execute, and offers expire after 5 minutes.

* **`/trade`** — card for card.
* **`/sell`** — offer one of your cards to a specific user for coins.
* **`/buy`** — offer coins to a specific user for one of their cards.

Execution is transactional and re-validates ownership, balance, and roster space at commit time. A buyer who currently holds an unrefunded bid on an open auction is blocked outright, so escrowed coins can't be double-spent into a P2P purchase.
