# EconSim Changelog

All notable changes to the Economy Simulator.

---

## [Current Version]

### April 26, 2026 — Full Code Review Overhaul (9 Changes)

#### 🔴 Bugs Fixed

- **`agent_produce()` double-assignment** — Quantity was set price-aware, then immediately overwritten with a random value. Now the price-aware quantity is preserved. `production_cost` now correctly scales with `quantity` (`price × uniform × quantity` instead of just `price × uniform`). Transaction amount corrected to use `production_cost`.

- **Factory build cost = 0** — `cost = 0` was forced after the ROI calculation, making all factory construction free for any agent with any balance. Calculated cost is now preserved — agents pay real money to build infrastructure, making factory ownership a strategic investment decision.

- **Steel chain UI mismatch** — The single `Iron+Coal → Steel` chain row showed only the Coal Mine, missing the Iron Mine and Iron Bars Mill. Split into two visible rows: `Iron → Iron Bars` (Iron Bars Mill, Iron Mine) and `Coal → Steel` (Steel Mill, Coal Mine). Both inputs to the Steel chain are now visible in the production chain display.

#### 🟡 Economy Tuning

- **Wealth redistribution fires every 10 ticks** — Previously fired every tick, constantly smoothing out natural economic dynamics and making individual decisions feel meaningless. Now runs via `WEALTH_REDIST_INTERVAL = 10`. Economy has 9 ticks of natural behavior between redistribution cycles. Same total tax collected over time, just batched.

- **Consumer budget increased** — Budget from `balance × 0.20` (max 2 units) to `balance × 0.40` (max 3 units). As prices rise, consumers were becoming irrelevant economic actors. Now they can participate meaningfully in the market longer.

- **Shop initial cash reduced** — From $50,000–$100,000 down to $5,000–$10,000. Shops were immediately becoming the dominant economic actor on tick 1, flooding the economy with money and skewing all metrics. Now well-capitalized but no longer distort the economy at startup.

#### 🟢 New Features

- **Processing chart now tracks activity, not inventory** — Dataset[1] previously showed `total_refined` (sum of refined goods sitting in agent inventories), which was static and meaningless as a processing rate. Now uses `processing_count` — number of `processing_log` entries in the last 10 ticks, a rolling count of actual processing events.

- **New Money Flow chart** — Fourth chart added to the dashboard showing money injection vs. sink per tick. Green bars: money entering the agent pool (shop sales, factory fees, mining fees). Red bars: money leaving the agent pool (production costs, shop purchases, factory building costs). Makes economy health readable at a glance. Three new columns in `history` table: `money_injected`, `money_sunk`, `processing_count`.

- **Infrastructure investment is now real** — Factory build costs (from tuning fix) mean agents must make deliberate investment decisions to expand. No longer free — the outcome of a decision that matters. Combined with factory upgrade paths, infrastructure is now a meaningful economic decision.

#### Engineering

- **`simulation_loop()` error handling added** — Previously bare `except:` swallowed all errors silently, causing the sim to stop with no visible indication of what went wrong. Now wraps `simulation_tick()` in try/except with traceback printing. Errors surface immediately.

- **DB migration for `history` schema** — `init_db()` creates the `history` table with the new columns (`money_injected`, `money_sunk`, `processing_count`) via `CREATE TABLE IF NOT EXISTS`, which does nothing on existing DBs. Migration script (`/tmp/migrate_ecsim.py`) adds the columns to live databases.

### Economy & Balance

- **Wealth Tax + Minimum Balance Guarantee** *(Apr 25, 2026)*
  - 3% tax on balances over $5,000 per tick, collected and redistributed equally to all agents
  - Agents below $50 receive a welfare top-up (capped at 5% of total economy per tick)
  - Prevents rich agents from pulling too far ahead and keeps broke agents solvent

- **Shop Investment Costs Reduced** *(Apr 25, 2026)*
  - All shop costs reduced 75-80% to make them accessible to more agents
  - Bakery: $25,000 → $5,000 | Jeweler: $50,000 → $10,000
  - Carpenter: $20,000 → $5,000 | Blacksmith: $25,000 → $5,000

- **Fuel Price Cut + Consumer Welfare** *(Apr 25, 2026)*
  - Fuel base_price reduced: $40 → $25 (37% cost cut per unit)
  - Consumers with balance < $500 receive income supplement each tick
  - Supplement: `min(100, 500 - balance) * 0.5` — keeps consumers solvent
  - All 8 agents now growing steadily with no bankruptcies

- **Starting Capital Increased** *(Apr 25, 2026)*
  - Economy now starts with $71,000 total (8 agents with varied balances)
  - Previously started at $8,000 (all agents at $1,000 each)
  - Agent starting balances: Frank $18k, Dave $12k, Carol $10k, Henry $8.5k, Bob $7k, Alice $6k, Diana $5k, Grace $4.5k

### Shops

- **Dedicated Shop Opening Mechanic** *(Apr 25, 2026)*
  - 5% chance per tick to open a new shop (separate from random event system)
  - Previously was one of 10 random events (~0.5% chance per tick)
  - Ensures shops appear consistently without relying on RNG

- **Shop Uniqueness Enforcement** *(Apr 25, 2026)*
  - Only one shop of each type can exist at a time (Bakery, Jeweler, Carpenter, Blacksmith, Refinery)
  - Previously checked by `input_good` which could allow duplicates
  - Now checks by shop name

- **Refinery / Fuel Mill Conflict Resolved** *(Apr 25, 2026)*
  - Fuel Mill (factory) changed from Coal → Fuel to Oil → Fuel
  - Refinery shop was later removed entirely (redundant)
  - Coal now used primarily for Steel production

### Production

- **Shops Own Dedicated Mills** *(Apr 25, 2026)*
  - Each shop spawns with a private mill matching its input type (Jeweler→Gold Bars Mill, etc.)
  - Mills are `shop_id`-linked to the owning shop, cannot be used by other agents
  - Shops auto-process raw materials → refined inputs → finished goods
  - Agents sell raw materials (Iron, Gold, Lumber, Flour) directly to shops at 90%
  - `factories` gains `shop_id` column; `shops` gains `mill_id` column
  - Mills process at 0% fee (internal to shop)
  - New `Iron Mine` produces `Iron` directly (no intermediate ore step)
  - Feeds into existing `Iron Bars Mill` production chain
  - 5% chance per tick for an agent to build one; only one can exist
  - 25% extraction chance per tick — customer pays fee, owner earns revenue
  - New tables: `mines`, `mining_log`; new API: `GET /api/mines`
  - Production chain display updated to show Iron Mine badge

- **Market Sell Fallback** *(Apr 25, 2026)*
  - `sell_shop` action falls back to `agent_sell_to_market()` when no shop will buy
  - Agents sell any good at 85% of market price
  - Prevents hoarding deadlock when a shop closes (e.g. Jeweler going bankrupt)
  - New transaction type: `market_sell`
  - All 6 mines now exist: Iron Mine, Coal Mine, Gold Mine, Oil Mine, Wheat Farm, Wood Mine
  - Each mine produces its raw good directly (no intermediate ore)
  - Feeds into production chains: Iron→Iron Bars Mill, Coal→Steel Mill, etc.
  - Production rate cut: `AGENT_PRODUCE_CHANCE = 0.3 → 0.1`
  - CHAIN display shows mine badge for all 6 raw material sources
  - 5% chance per tick for agent to build any unbuilt mine

- **Market Table Not Seeded** *(Apr 25, 2026)*
  - `init_db()` was creating the market table but not populating it
  - `simulation_tick()` has an early-exit guard: `if not agents or not market_goods: return`
  - With an empty market table, every tick would exit early — tick count never incremented
  - Fixed: `init_db()` now seeds all 16 market goods (6 raw + 6 refined + 4 finished)

- **sim_reset() Overwriting Balances** *(Apr 25, 2026)*
  - Reset endpoint was hardcoding all agents to $1,000 instead of using seed balances
  - Fixed: now re-inserts agents with their proper INITIAL_AGENTS values

- **Tick Count Stuck at Zero** *(Apr 25, 2026)*
  - Root cause was the empty market table (see above)
  - After fixing market seeding, ticks now count correctly

### UI / Display

- **Production Chain Display Overhaul** *(Apr 25, 2026)*
  - Changed from cramped inline layout to clean card-style rows
  - Each chain on its own row: `[Raw] → [Refined] → [Finished]` with badges on the right
  - Added Oil → Fuel and Coal → Steel chains to the display
  - Renamed Iron Mill → Iron Bars Mill and Gold Mill → Gold Bars Mill to match actual factory names
  - Shops show OPEN/CLOSED status instead of just a count

---

## [Original Version — Simulator Inception]

### Architecture

- **Flask-based Web Dashboard**
  - Runs on port 5002
  - SQLite database (`ecsim.db`) for persistent state
  - WAL mode enabled for concurrent reads during simulation
  - Endpoints: `/api/agents`, `/api/market`, `/api/history`, `/api/events`, `/api/shops`, `/api/factories`, `/api/transactions`, `/api/simulation/*`

- **Multi-threaded Simulation**
  - Simulation loop runs in a background daemon thread
  - Configurable tick interval (default 1.0 second)
  - Start/stop/reset/speed API endpoints

### Agents (8 total)

| Name | Type | Starting Balance | Inventory |
|------|------|-----------------|------------|
| Frank | trader | $18,000 | Gold Bars x1, Steel x1, Tools x1 |
| Dave | processor | $12,000 | Iron x4, Coal x4 |
| Carol | processor | $10,000 | Wheat x4, Iron x3, Coal x2 |
| Henry | producer | $8,500 | Gold x3, Iron x4, Coal x3 |
| Bob | producer | $7,000 | Iron x5, Coal x4 |
| Alice | producer | $6,000 | Wheat x6, Wood x4 |
| Diana | consumer | $5,000 | Bread x2, Furniture x1 |
| Grace | consumer | $4,500 | Flour x2, Lumber x2 |

### Production Chains (Stage 1 — Factories/Mills)

| Mill | Input | Output | Base Price |
|------|-------|--------|------------|
| Flour Mill | Wheat x2 | Flour | $45 |
| Iron Bars Mill | Iron x2 | Iron Bars | $120 |
| Gold Bars Mill | Gold x2 | Gold Bars | $1,200 |
| Lumber Mill | Wood x2 | Lumber | $65 |
| Steel Mill | Iron Bars x1 + Coal x1 | Steel | $280 |
| Fuel Mill | Oil x2 | Fuel | $40 |

### Shops (Stage 2 — Finish Goods)

| Shop | Input | Output | Buy Price Mult | Initial Cash |
|------|-------|--------|---------------|-------------|
| Bakery | Flour x3 | Bread | 0.95 | $5,000 |
| Jeweler | Gold Bars x2 | Jewelry | 0.95 | $10,000 |
| Carpenter | Lumber x3 | Furniture | 0.95 | $5,000 |
| Blacksmith | Steel x2 | Tools | 0.95 | $5,000 |

### Market Goods (16 total)

**Raw Goods (6):** Wheat, Iron, Gold, Oil, Wood, Coal

**Refined Goods (6):** Flour, Iron Bars, Gold Bars, Lumber, Steel, Fuel

**Finished Goods (4):** Bread, Jewelry, Furniture, Tools

### Agent Types & Behaviors

- **Producer** — Can produce raw goods (Wheat, Iron, Gold, Oil, Wood, Coal)
- **Processor** — Can use factories/mills to refine raw goods
- **Consumer** — Buys finished goods, generates demand
- **Trader** — Starts with diverse inventory, facilitates trade

### Agent Action Probabilities

- **Producer:** produce 45%, factory 10%, process 5%, sell_shop 12%, buy_shop 8%, consume 10%, trade 5%, build 5%
- **Processor:** produce 20%, factory 30%, process 10%, sell_shop 15%, buy_shop 10%, consume 10%, trade 5%, build 5%

### Economic Events (10 total, ~5% chance per tick)

| Event | Effect |
|-------|--------|
| Gold Rush | Random agent gains $2,000–$5,000 |
| Recession | All agents happiness -0.2 |
| Prosperity | All agents happiness +0.3 |
| Tech Boom | 2 random factories upgraded (+1 level, -10% fees) |
| Supply Shock | Random good supply -15 to -70 units |
| Inflation | Economy-wide price multiplier applied to all goods |
| Refined Demand | Random refined good demand +30 |
| Export Boom | Random raw good demand +50 |
| Factory Fire | Random factory destroyed |
| New Competitor | Random agent gets +$1,000 |

### History Tracking

- Recorded every 10 ticks
- Tracks: total_money, gini_coefficient, num_transactions, avg_price, inflation_rate, total_refined, factories_active, shops_count

### GINI Coefficient

- Measures wealth inequality across agents (0 = perfect equality, 1 = maximum inequality)
- Calculated using the Lorentz formula: `gini = (2 * weighted_sum) / (n * cumsum) - (n + 1) / n`
- US reference: ~0.38–0.41 | Scandinavia: ~0.25–0.30 | Extreme inequality: >0.5

### Configuration Constants

```
AGENT_PRODUCE_CHANCE = 0.3
AGENT_PROCESS_CHANCE = 0.2
AGENT_FACTORY_CHANCE = 0.35
AGENT_CONSUME_CHANCE = 0.4
AGENT_TRADE_CHANCE = 0.5
MIN_BALANCE = 10.0
EVENT_CHANCE = 0.05
WEALTH_TAX_RATE = 0.03
WEALTH_TAX_THRESHOLD = 5000.0
WEALTH_MINIMUM = 50.0
tick_interval = 1.0 (default)
```

---

## Original Design Issues (Pre-Fixes)

- All 8 agents started with $1,000 = $8,000 total economy
- Shops cost $20,000–$50,000 — only Frank could afford even the cheapest
- Shop opening was a rare random event (~0.5% per tick)
- No wealth redistribution — rich agents compounded, poor agents stayed broke
- Fuel Mill and Refinery both used Coal → Fuel (conflict, later resolved — Refinery removed)
- Market table empty on first run, causing ticks to do nothing
- Production chain display showed only 5 chains (no Oil) with messy inline formatting