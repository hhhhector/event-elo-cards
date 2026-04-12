# **Single Source of Truth (SSOT): Esports Trading Card Economy**

## **1\. The Core Valuation Math**

* **Market Value is Bank Value:** No exit taxes or hidden fees. If the bank value is 5,000, selling to the bank yields exactly 5,000.  
* **The Anchor Formula:** Bank Value \= 10000 \* (Elo / 2200)^3. X-Tier cards are legendary; D-Tier cards are extremely cheap.  
* **Daily Dividends:** Yield is exactly Bank Value / 10 paid every 24 hours. This creates a solid 10-day ROI that makes holding profitable but keeps the "Sell to Bank" button highly tempting during Elo spikes.

## **2\. Drop Mechanics (Weaponized RNG)**

* **The Heartbeat (Railway-Proof):** The bot uses a 1-minute discord.ext.tasks loop that checks a system\_state table in Supabase for the next\_drop\_timestamp. This prevents timer amnesia on server restarts.  
* **The Timing (Exponential Distribution):** Average of 60 minutes between drops, strictly clamped between 15 and 120 minutes. Players never know exactly when the next drop hits, forcing them to hold liquid cash.  
* **The Supply (Poisson Distribution):** Average of 4 cards per drop, clamped between 1 and 8 cards.  
* **Auction Overlap:** None. Auctions are isolated 10-minute events to keep the Discord chat clean.  
* **Infinite Generations:** No global hard limits on card copies. Multiple players can own the same player.

## **3\. Bidding Rules & UI**

* **The "Pick One" Rule:** Players can only bid on *one* card per multi-card drop. This forces whales to fight each other over S-Tiers, leaving the D-Tiers uncontested for beginners.  
* **The Dynamic Spread (Anti-Exploit):**  
  * D-Tier starting bids: \~40% of Bank Value (High Arbitrage).  
  * X-Tier starting bids: \~90% of Bank Value (Zero Arbitrage, forces holding for yield).  
* **Bidding Interface:** Bids are submitted via a Discord text Modal rather than clicking buttons. This completely prevents 1-coin penny wars.  
* **Minimum Increment:** 5% of Bank Value for all tiers. Allows rich players to instabid large amounts while keeping penny wars impossible.
* **Currency Symbol:** ⛃ placed before the number (e.g., ⛃ 3,233).

## **4\. Player Inventory & Progression**

* **The Starter Pack:** A manual /register command injects ⛃ 300 for a new player to win an uncontested D-Tier and enter the arbitrage hustle.  
* **The 10-Card Roster Cap:** The ultimate economy saver. All cards held generate yield, but the hard 10-card cap stops infinite compounding. To get an 11th card, a player *must* liquidate an existing one. Duplicates of the same card are fully allowed.
* **Roster Check at Bid Time:** If a player's roster is full, their bid is rejected immediately with a message to sell a card first.
* **The Progression Loop:**
  * *Early Game:* Buy cheap D-tiers, instantly sell to Bank for the arbitrage spread.  
  * *Mid Game:* Roster gets full. Stop flipping, start saving dividends to upgrade slots to A-Tiers.  
  * *Late Game:* Yieldmaxxing. Spending massive wealth outbidding other whales for God-tier cards.

## **5\. Wealth Sinks (Inflation Control)**

* **Roster Expansions:** Expanding the roster capacity beyond 10 costs an absurd, exponential amount of money.  
* **Cosmetic Flexes:** Upgrading a card to "Holographic" costs 3x its Bank Value. Changes nothing about stats, just makes the embed glow and look prestigious.  
* **Sponsored Drops:** Whales can pay 15,000 ⛃ to force a public drop off-schedule with a banner announcing they funded it. (No VIP fast-passes or Gacha mechanics—they still have to bid like everyone else).
