# MinerDashboard Changelog

All notable changes to the CKB Miner Dashboard are logged here.

---

## [Unreleased] - 2026-04-23

### Fixed
- **Miner hashrate scaling bug** — `api_status()` was multiplying miner `current_hashrate` and `avg_hashrate` by `×1e12` (TH/s scale) when the raw value from `/cpb/hshistory` is already H/s. Resulted in ~1,100,000 TH/s displayed for 1.1 TH/s miners. Fixed to `×1e6`.
- **Missing `network_diff` in API response** — `api_status()` was returning `network_hashrate` but not `network_diff`. Dashboard header expected both `Net:` and `Diff:` values. Added `combined["network_diff"] = net_data.get("current_difficulty", 0)`.
- **Missing `_network_current_cache` declaration** — During cleanup, the `_network_current_cache` and `_network_current_fetch_time` variables for the `/api/network/current` endpoint were accidentally removed, causing a `NameError` and 500 errors. Re-added the declarations.

### Changed
- **Removed unused `math` import** — Replaced with targeted `from math import sqrt` to avoid importing the entire module.
- **Cleaned up duplicate cache declarations** — Removed redundant `_network_current_cache` / `NETWORK_CURRENT_CACHE_SECONDS` declarations that were causing conflicts.

---

## [Unreleased] - 2026-04-22

### Added
- **7d Earned card** — displays actual 7-day earnings from 2miners `sumrewards` API (interval 604800), placed between 24h and 30d cards. Shows CKB + USD value with same color styling as other earnings cards.

### Changed
- **Pool Hashrate** card (renamed from "Total Hashrate") — now explicitly shows the pool's `currentHashrate` (live hashrate reported by the pool, summed across all workers) rather than being ambiguous about the source.

### Removed
- **Daily Est. card** — calculation was unreliable and produced incorrect values. Redundant with the 24h Earned card which shows actual earnings.

### Fixed
- **Duplicate `ckbPrice` variable declaration** — `ckbPrice` was declared twice in the same scope (once in the 24h block and again in the daily est block), causing a JavaScript `SyntaxError`. Removed the duplicate declaration.

---

## [Unreleased] - 2026-04-20

### Added
- **"Last Share" per miner** — Shows time since each miner last submitted a share to the pool, pulled from 2miners `lastBeat`. Live-updates every second. Color-coded: green <1m, yellow <5m, red >5m.
- **README section: Adapting for other Goldshell CKB miners** — Documents the `/mcb/status` endpoint, how to adapt the miner config, and notes that pool data works for any CKB miner.

### Changed
- **Removed Temperature card from miner cards** — CK-Box doesn't expose temperature data via its API, card always showed `--`. Removed dead code and CSS.
- **load_config() called on module import** — Fixes gunicorn/WSGI deployment where `main()` never runs.
- **Lazy pool data fetch on first API call** — Pool data is now fetched on demand rather than only at startup, fixing cloud deployments.
- **WALLET_ADDRESS env var override** — Wallet address can be set via environment variable (useful for cloud platforms).
- **Dashboard_Run.sh made portable** — Uses `$(dirname "$0")` instead of hardcoded path.
- **README cleaned up** — Removed Render deployment docs, hidden real wallet address, hidden miner IPs, updated screenshots.

### Removed
- **render.yaml** — Render deployment not practical without access to local miners. Tailscale Funnel is the recommended remote access method.
- **gunicorn from requirements.txt** — Flask dev server is sufficient for local/self-hosted use.
- **Old log files** — `miner.log` and `miner_monitor.log` no longer written.

### Fixed
- **GitHub repo setup** — Config, logs, and data files are properly gitignored.
- **Module-level config initialization** — Config loads on import for WSGI compatibility.

---

## [Unreleased] - 2026-04-19

### Added
- **"Miners Online" stat card** — Shows `online / total` miner count in the top stats row. Color-coded: green when all online, yellow when some offline, red when all offline.

### Changed
- **"Current Luck" → "Pool Luck"** — Renamed the luck stat card label for clarity.
- **Removed "Your Blocks (24h)" card** — Replaced with the new "Miners Online" card.
- **USD/CKB color coding on Earned cards** — USD amounts now display in green (`--accent-green: #3fb950`) with `!important` to ensure they render correctly regardless of CSS cascade. CKB amounts display in blue (`--accent-blue: #58a6ff`). Applied to both 24h Earned and 30d Earned cards.

### Mobile Polish — All Navigation Pages

Comprehensive mobile-first redesign across all secondary pages. Design standards now consistent with the main dashboard.

#### blocks.html 🧱
- Added `.table-wrapper` with `overflow-x: auto` and `-webkit-overflow-scrolling: touch` for horizontal table scroll on mobile
- Consistent header with pill-style back-link button (← Dashboard)
- Unified CSS variables matching dashboard theme
- Improved table hover states with subtle background tint
- Loading spinner with accent-yellow (`--accent-yellow`) color
- Error state with red background tint and border

#### transactions.html 🔄
- Same horizontal scroll fix as blocks.html
- Pill-style back-link button matching other pages
- Accent color changed from hardcoded purple to CSS variable `--accent-purple`
- Table row hover states with purple tint
- Loading spinner uses accent-purple color

#### payments.html 💳
- Horizontal scroll wrapper for payments table
- Summary cards grid changed from fixed `minmax(180px, 1fr)` to `minmax(140px, 1fr)` for better mobile fit
- Table column headers shortened: "Tx" instead of "Transaction", "USD" instead of "Value (USD)", etc.
- Date and time now stacked in their own cell (date bold, time + relative below)
- Back-link now uses consistent pill style
- All colors use CSS variables

#### calculator.html 🧮
- Header now uses flexbox with `flex-wrap: wrap` and `gap: 12px` — stacks vertically on mobile
- Title and back-link both center-aligned on mobile via `justify-content: center`
- Results grid changed to `grid-template-columns: 1fr 1fr` on desktop, `1fr` on mobile (`max-width: 480px` breakpoint)
- Added `inputmode="decimal"` and `inputmode="numeric"` attributes to all inputs for correct mobile keyboard
- Input font-size set to `16px` to prevent iOS zoom on focus
- Calc button includes icon (📊) and center-aligned text
- Back-link uses consistent pill style

#### market.html 📈
- Market cards grid changed to `repeat(auto-fit, minmax(160px, 1fr))` — adapts to any screen width
- Cards have `transform: translateY(-2px)` on hover for subtle lift effect
- Chart section uses consistent card styling (same bg, border, radius, shadow as other pages)
- Refresh button in chart header (not just at bottom)
- Chart wrapper has fixed height with `!important` overrides for canvas
- Back-link uses consistent pill style
- Loading spinner uses accent-green color

#### statistics.html 📉
- Stats grid uses `repeat(auto-fit, minmax(200px, 1fr))` — auto-wraps on any screen
- Epoch card spans 2 columns on desktop (`grid-column: span 2`) — single column on mobile (`max-width: 600px`)
- Progress bar for epoch progress uses purple gradient matching accent-purple
- Refresh button centered below cards with green gradient styling
- Back-link uses consistent pill style
- Cards have hover lift effect

#### network.html 📊
- Already well-styled — minor cleanup to back-link to match consistent pill style
- Verified all existing mobile breakpoints work correctly

### Design Standards Applied (All Pages)

- **CSS variables** for all colors — single source of truth via `:root`
- **Fluid typography** with `clamp()` — e.g. `clamp(20px, 5vw, 26px)` for headings
- **Pill-style back links** — `border-radius: var(--radius-sm)`, icon + text, subtle bg + border
- **Loading spinners** — accent color matching each page's theme
- **Card hover effects** — `border-color` transitions, `transform: translateY(-2px)` lift
- **Touch-friendly** — minimum 44px tap targets on buttons
- **Border-radius consistency** — `var(--radius: 12px)` for cards, `var(--radius-sm: 8px)` for buttons/inputs
- **Box shadows** — `var(--shadow: 0 4px 12px rgba(0,0,0,0.3))` for cards, `var(--shadow-lg)` for larger elements
- **Font variant** — `font-variant-numeric: tabular-nums` on all numeric values for alignment

---

## [1.0.0] - 2026-04-14

### Added
- Initial MinerDashboard release
- Main dashboard with miner hashrate cards, pool stats, hashrate chart
- Blocks page
- Calculator page
- Market page
- Network Hashrate page
- Payments page
- Statistics page
- Transactions page
