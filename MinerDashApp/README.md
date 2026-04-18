# MinerDash App

Monitor your mining rigs from your phone. Works with any coin.

## Supported Coins

| Coin | Pool Preset |
|------|-------------|
| 🔴 Nervos CKB | 2miners |
| 🐕 Dogecoin | 2miners |
| LTC Litecoin | 2miners |
| Ξ Ethereum | Ethermine |
| Ξ Ethereum Classic | 2miners |
| 🌲 Ravencoin | 2miners |
| CFX Conflux | 2miners |
| α Alephium | 2miners |
| ◇ Sia | 2miners |
| █ Cortex | 2miners |
| K Kaspa | 2miners |
| ◎ Solana | 2miners |
| λ Aleo | 2miners |
| ⚙️ Custom | Any URL |

## First-Launch Wizard

1. **Pick your coin** — tap a preset or Custom for any coin
2. **Server & Miners** — enter MinerMonitor server IP + miner names/IPs (1–50)
3. **Confirm** — review and launch

Settings saved locally and synced to your Flask backend.

## Architecture

```
Mobile APK ←──fetch──→ MinerMonitor Flask Server ←──polls──→ ASIC miners
                            ↕
                      Pool API (2miners, etc.)
```

The APK talks to your Flask backend (`http://YOUR_SERVER:5000`), not directly to miners.

## APK Location

```
MinerDashApp/MinerDash-v1.0.0.apk  (3.7MB)
```

## MinerMonitor Server

Your Flask server must be running:

```bash
cd ~/.openclaw/workspace/MinerDashboard
python3 miner_monitor.py
```

Miner IPs and wallet are synced to the backend via `PUT /api/miners`.

## Rebuild APK

Requires Android SDK at `/home/dalton/android-sdk`:

```bash
cd MinerDashApp
npm run cap:build
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`
