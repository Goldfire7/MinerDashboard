# Goldshell CK-Box Dashboard

A self-hosted dashboard for monitoring Goldshell CK-Box miners via the 2miners pool API.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Pool Statistics** — Real-time hashrate, earnings, luck, and shares from 2miners
- **Block Tracking** — View recent blocks found by your workers
- **Payment History** — Payout records with USD/CKB breakdown
- **Market Data** — CKB price and portfolio value
- **Network Stats** — CKB network difficulty and hashrate
- **Calculator** — Estimate earnings at different hashrate levels
- **Responsive UI** — Works on desktop and mobile browsers

## Requirements

- Python 3.11+
- Goldshell CK-Box miners on your local network
- A 2miners account with CKB wallet

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Create a `config.json` in the project root:

```json
{
  "wallet": "ckb1qyqfv9d5vr7x5ss8wuv6a7pyuazwyltjgh7qdvcyqs",
  "miners": [
    {"name": "CK_Box_1", "ip": "192.168.0.61"},
    {"name": "CK_Box_2", "ip": "192.168.0.72"}
  ],
  "poll_interval": 5,
  "history_points": 2880
}
```

Or set environment variables (useful for cloud deployment):

| Variable | Description | Default |
|----------|-------------|---------|
| `WALLET_ADDRESS` | Your CKB wallet address | — |
| `POLL_INTERVAL` | Seconds between polls | `5` |

### 3. Run

```bash
python3 miner_monitor.py
```

Open [http://localhost:5000](http://localhost:5000)

### Remote Access

To access your dashboard from outside your home network, use [Tailscale Funnel](https://tailscale.com/funnel):

```bash
# Install Tailscale and authenticate
tailscale up

# Enable funnel — exposes port 5000 publicly via HTTPS
tailscale funnel 5000

# Check the public URL
tailscale funnel status
```

## Configuration

### `config.json`

| Key | Description | Default |
|-----|-------------|---------|
| `wallet` | CKB wallet address (for 2miners) | Required |
| `miners` | List of miner configs (see below) | `[]` |
| `poll_interval` | Seconds between API polls | `5` |
| `history_points` | Data points to retain | `2880` |

### Miner Config

Each miner entry needs:

```json
{"name": "CK_Box_1", "ip": "192.168.0.61"}
```

- `name` — Display name (can be anything)
- `ip` — Local IP of the miner

### Environment Variables

| Variable | Description |
|----------|-------------|
| `WALLET_ADDRESS` | Overrides `wallet` in config.json |
| `POLL_INTERVAL` | Overrides poll interval |
| `PORT` | Web server port (default `5000`) |

## Cloud Deployment

### Render (Free Tier)

1. Fork this repo
2. Create a new **Blueprint** on [Render](https://render.com)
3. Connect your GitHub repo
4. Add environment variable: `WALLET_ADDRESS`
5. Deploy

Render auto-detects the `render.yaml` file.

> **Note:** On Render's free tier, miners must be reachable from Render's servers. For local miners, you'll need Tailscale or another VPN to expose your network.

## Project Structure

```
MinerDashboard/
├── miner_monitor.py      # Main Flask app + polling logic
├── config.json           # User configuration (gitignored)
├── requirements.txt     # Python dependencies
├── render.yaml           # Render deployment config
├── templates/            # HTML templates
│   ├── dashboard.html
│   ├── blocks.html
│   ├── payments.html
│   └── ...
└── data/                 # Runtime data (gitignored)
    ├── hashrate_history.json
    ├── earnings_history.json
    └── ...
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard UI |
| `GET /api/status` | Miner + pool status |
| `GET /api/history` | Historical hashrate data |
| `GET /api/shares` | Pool shares data |
| `GET /api/blocks` | Recent blocks |
| `GET /api/payments` | Payment history |
| `GET /api/rewards` | Block rewards |
| `GET /api/network/current` | Network difficulty |
| `GET /api/network/hashrate` | Network hashrate |
| `GET /api/market/data` | Market cap, volume, price |
| `GET /api/earnings` | Daily earnings history |

## License

MIT
