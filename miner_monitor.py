#!/usr/bin/env python3
"""
Miner Monitor - Goldshell CK-Box Dashboard
Polls miners for hashrate and status data, serves dashboard.
"""

import json
import logging
import time
import http.client
from math import sqrt
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request
import requests
import threading
from pathlib import Path

# Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Config
CONFIG_FILE = Path(__file__).parent / "config.json"
UPTIME_FILE = Path(__file__).parent / "data" / "uptime.json"
EARNINGS_FILE = Path(__file__).parent / "data" / "earnings_history.json"
BLOCK_SNAPSHOT_FILE = Path(__file__).parent / "data" / "block_snapshots.json"
HISTORY_FILE = Path(__file__).parent / "data" / "hashrate_history.json"
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

app = Flask(__name__)

# Global state
miner_data = {}
miner_history = {}
miner_uptime = {}
pool_data = {}
earnings_history = []  # List of {date, ckb_earned, usd_value, ckb_price}
config = {}


def load_config():
    global config
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    else:
        config = {"miners": [], "poll_interval": 30}
    # Env var overrides — useful on cloud platforms like Render
    import os
    if os.environ.get("WALLET_ADDRESS"):
        config["wallet"] = os.environ["WALLET_ADDRESS"]
    if os.environ.get("POLL_INTERVAL"):
        try:
            config["poll_interval"] = int(os.environ["POLL_INTERVAL"])
        except ValueError:
            pass
    logger.info(f"Loaded config: {len(config.get('miners', []))} miners, wallet: {config.get('wallet', 'not set')[:10]}...")


def save_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

# Initialize config on module load (needed for gunicorn/WSGI)
load_config()


def load_earnings_history():
    """Load persisted earnings history."""
    global earnings_history
    if EARNINGS_FILE.exists():
        with open(EARNINGS_FILE) as f:
            earnings_history = json.load(f)
    else:
        earnings_history = []
    logger.info(f"Loaded earnings history: {len(earnings_history)} days")


def save_earnings_history():
    """Persist earnings history to disk."""
    with open(EARNINGS_FILE, 'w') as f:
        json.dump(earnings_history, f, indent=2)


def load_block_snapshots():
    """Load persisted block snapshots for daily aggregation."""
    if BLOCK_SNAPSHOT_FILE.exists():
        with open(BLOCK_SNAPSHOT_FILE) as f:
            return json.load(f)
    return {}


def save_block_snapshots(snapshots):
    """Persist block snapshots to disk."""
    with open(BLOCK_SNAPSHOT_FILE, 'w') as f:
        json.dump(snapshots, f, indent=2)


def calculate_daily_earnings_from_blocks(rewards_list, ckb_price):
    """
    Calculate daily earnings by aggregating actual block rewards by calendar day.
    Includes all blocks (confirmed + immature) for each day to match 2miners behavior.
    Orphan blocks are skipped.
    """
    from datetime import datetime, timezone
    
    daily = {}
    
    for r in rewards_list:
        ts = r.get("timestamp", 0)
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        ckb = to_ckb(r.get("reward", 0))
        orphan = r.get("orphan", False)
        
        # Skip orphans only
        if orphan:
            continue
        
        if day not in daily:
            daily[day] = {"ckb_earned": 0, "ckb_price": ckb_price}
        
        daily[day]["ckb_earned"] += ckb
    
    # Convert to list format
    result = []
    for date, data in sorted(daily.items()):
        result.append({
            "date": date,
            "ckb_earned": data["ckb_earned"],
            "usd_value": data["ckb_earned"] * data["ckb_price"],
            "ckb_price": data["ckb_price"]
        })
    
    return result


def track_daily_earnings():
    """Track daily earnings by aggregating actual block rewards by calendar day."""
    global earnings_history, pool_data
    
    rewards = pool_data.get("rewards", [])
    ckb_price = pool_data.get("ckb_price", 0)
    
    if not rewards:
        return
    
    # Load existing snapshots
    snapshots = load_block_snapshots()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Build set of existing block timestamps we already have
    existing_timestamps = set()
    for date, blocks in snapshots.items():
        for b in blocks:
            existing_timestamps.add(b.get("timestamp", 0))
    
    # MERGE new blocks with existing snapshots (don't replace!)
    # This ensures we capture all blocks across multiple polls
    for r in rewards:
        ts = r.get("timestamp", 0)
        # Only add if we don't already have this block
        if ts not in existing_timestamps:
            day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if day not in snapshots:
                snapshots[day] = []
            snapshots[day].append({
                "timestamp": ts,
                "reward": r.get("reward", 0),
                "orphan": r.get("orphan", False),
                "immature": r.get("immature", False)
            })
            existing_timestamps.add(ts)
    
    # Keep only last 10 days of snapshots to manage memory
    snapshot_dates = sorted(snapshots.keys())[-10:]
    snapshots = {k: snapshots[k] for k in snapshot_dates}
    
    save_block_snapshots(snapshots)
    
    # Calculate earnings from all snapshots
    all_rewards = []
    for date, blocks in snapshots.items():
        for b in blocks:
            all_rewards.append({
                "timestamp": b["timestamp"],
                "reward": b["reward"],
                "orphan": b.get("orphan", False),
                "immature": b.get("immature", False)
            })
    
    new_earnings = calculate_daily_earnings_from_blocks(all_rewards, ckb_price)
    
    # Keep last 90 days
    if len(new_earnings) > 90:
        new_earnings = new_earnings[-90:]
    
    earnings_history = new_earnings
    save_earnings_history()


def load_uptime():
    """Load persisted uptime data."""
    global miner_uptime
    if UPTIME_FILE.exists():
        with open(UPTIME_FILE) as f:
            miner_uptime = json.load(f)
    
    # Normalize keys to use underscores and clean up old hyphen keys
    normalized = {}
    for key, value in miner_uptime.items():
        normalized_key = key.replace("-", "_")
        normalized[normalized_key] = value
    miner_uptime = normalized
    
    # IMPORTANT: Reset all start_time and total_seconds to None/0 on load!
    # This ensures we track uptime from when the monitor starts/restarts,
    # not from stale data before a miner reboot or monitor restart.
    for key in miner_uptime:
        if miner_uptime[key].get("start_time") is not None:
            logger.info(f"Resetting uptime for {key} (was {miner_uptime[key]['start_time']})")
            miner_uptime[key]["start_time"] = None
            miner_uptime[key]["total_seconds"] = 0
    
    logger.info(f"Loaded uptime data for {len(miner_uptime)} miners")


def load_history():
    """Load persisted hashrate history."""
    global miner_history
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                miner_history = json.load(f)
            logger.info(f"Loaded hashrate history: {sum(len(v) for v in miner_history.values())} total points")
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")
            miner_history = {}

def save_history():
    """Persist hashrate history to disk."""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(miner_history, f)
    except Exception as e:
        logger.warning(f"Failed to save history: {e}")

_last_history_save = 0
HISTORY_SAVE_INTERVAL = 300  # Save history every 5 minutes

def save_uptime():
    """Persist uptime data to disk."""
    # Normalize all keys to use underscores before saving
    normalized = {}
    for key, value in miner_uptime.items():
        normalized[key.replace("-", "_")] = value
    with open(UPTIME_FILE, 'w') as f:
        json.dump(normalized, f, indent=2)


def to_ckb(x): return x / 1e8

def fetch_pool_stats(wallet_address):
    """Fetch actual mining stats from 2miners API."""
    if not wallet_address:
        return None
    try:
        conn = http.client.HTTPSConnection("ckb.2miners.com")
        conn.request("GET", f"/api/accounts/{wallet_address}")
        res = conn.getresponse()
        if res.status == 200:
            data = json.loads(res.read().decode("utf-8"))
            return {
                "hashrate": data.get("hashrate", 0),
                "current_hashrate": data.get("currentHashrate", 0),
                "reward_24h": to_ckb(data.get("24hreward", 0)),
                "blocks_24h": data.get("24hnumreward", 0),
                "luck": data.get("currentLuck", 0),
                "pending": to_ckb(data.get("stats", {}).get("balance", 0)),
                "min_payout": to_ckb(data.get("config", {}).get("minPayout", 50000000000)),
                "workers": data.get("workers", {}),
                "sumrewards": data.get("sumrewards", []),
                "rewards": data.get("rewards", [])  # Full rewards array for daily aggregation
            }
    except Exception as e:
        logger.warning(f"Failed to fetch pool stats: {e}")
    return None


def fetch_pool_shares(wallet_address, interval="5m"):
    """Fetch shares data from 2miners API."""
    if not wallet_address:
        return None
    try:
        conn = http.client.HTTPSConnection("ckb.2miners.com")
        conn.request("GET", f"/api/accounts/{wallet_address}/shares/{interval}")
        res = conn.getresponse()
        if res.status == 200:
            data = json.loads(res.read().decode("utf-8"))
            return data
    except Exception as e:
        logger.warning(f"Failed to fetch pool shares: {e}")
    return None


def fetch_pool_blocks(wallet_address):
    """Fetch blocks data from 2miners API."""
    if not wallet_address:
        return None
    try:
        conn = http.client.HTTPSConnection("ckb.2miners.com")
        conn.request("GET", "/api/blocks")
        res = conn.getresponse()
        if res.status == 200:
            data = json.loads(res.read().decode("utf-8"))
            return data
    except Exception as e:
        logger.warning(f"Failed to fetch blocks: {e}")
    return None


def fetch_pool_payments(wallet_address):
    """Fetch payments data from 2miners account API."""
    if not wallet_address:
        return None
    try:
        conn = http.client.HTTPSConnection("ckb.2miners.com")
        conn.request("GET", f"/api/accounts/{wallet_address}")
        res = conn.getresponse()
        if res.status == 200:
            data = json.loads(res.read().decode("utf-8"))
            payments = data.get("payments", [])
            payments_total = data.get("paymentsTotal", len(payments))
            if payments:
                return {"payments": payments, "paymentsTotal": payments_total}
    except Exception as e:
        logger.warning(f"Failed to fetch payments: {e}")
    return None


# Track last successful price fetch to avoid rate limiting
_last_price_fetch = 0
_price_cache = None

# Network hashrate cache
_network_hashrate_cache = None
_network_hashrate_fetch_time = 0
NETWORK_HASHRATE_CACHE_SECONDS = 3600  # Cache for 1 hour

# Network current cache (for /api/network/current endpoint)
_network_current_cache = None
_network_current_fetch_time = 0
NETWORK_CURRENT_CACHE_SECONDS = 60  # Cache for 1 minute

# Network difficulty cache
_network_difficulty_cache = None
_network_difficulty_fetch_time = 0
NETWORK_DIFFICULTY_CACHE_SECONDS = 3600  # Cache for 1 hour

def fetch_ckb_price():
    """Fetch CKB price from CoinGecko with rate limiting."""
    global _last_price_fetch, _price_cache
    
    # Only fetch once per 60 seconds to avoid rate limiting
    now = time.time()
    if now - _last_price_fetch < 60 and _price_cache is not None:
        return _price_cache
    
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=nervos-network&vs_currencies=usd", timeout=10)
        if resp.status_code == 429:
            logger.warning("CoinGecko rate limited, using cached price")
            return _price_cache
        resp.raise_for_status()
        data = resp.json()
        _price_cache = data.get("nervos-network", {}).get("usd", 0)
        _last_price_fetch = now
        return _price_cache
    except Exception as e:
        logger.warning(f"Failed to fetch CKB price: {e}")
    return _price_cache


def map_worker_to_miner(worker_name, miners):
    """Map 2miners worker name (ckbox1-4) to miner by IP or index."""
    # Parse worker number from name like "ckbox1"
    try:
        worker_num = int(worker_name.replace("ckbox", ""))
    except:
        return None
    
    # Match by index (1-based) to miners list
    if 0 < worker_num <= len(miners):
        return miners[worker_num - 1].get("name")
    return None


def fetch_json(ip, endpoint, timeout=5):
    """Fetch JSON from miner endpoint."""
    url = f"http://{ip}/{endpoint}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def poll_miner(miner):
    """Poll a single miner for data."""
    ip = miner["ip"]
    name = miner.get("name", ip)
    
    data = {
        "name": name,
        "ip": ip,
        "online": False,
        "last_update": None,
        "hashrate": [],
        "current_hashrate": None,
        "avg_hashrate": None,
        "hw_errors": 0,
        "status": {},
        "setting": {},
        "pools": [],
        "mac": None
    }
    
    # Fetch status
    status = fetch_json(ip, "mcb/status")
    if status:
        data["online"] = True
        data["status"] = status
        data["last_update"] = datetime.now().isoformat()
        
        # Extract HW errors from status (Goldshell reports hw_errors or errors)
        # Common field names: "hw_errors", "hwErrorRate", "errors"
        if "hw_errors" in status:
            data["hw_errors"] = status.get("hw_errors", 0)
        elif "hwErrorRate" in status:
            data["hw_errors"] = status.get("hwErrorRate", 0)
        elif "errors" in status:
            # errors might be a list or count
            errors_data = status.get("errors", [])
            if isinstance(errors_data, list):
                data["hw_errors"] = len(errors_data)
            else:
                data["hw_errors"] = errors_data
        elif "error_rate" in status:
            data["hw_errors"] = status.get("error_rate", 0)
        
        # Extract temperatures from status (Goldshell CK-Box reports chip/board temps)
        temps = []
        if "temperatures" in status:
            # temperatures is usually an array of chip temps
            temps = status.get("temperatures", [])
        elif "temp" in status:
            # temp might be an array or single value
            temp_data = status.get("temp", [])
            if isinstance(temp_data, list):
                temps = temp_data
            else:
                temps = [temp_data]
        elif "chips_temp" in status:
            temps = status.get("chips_temp", [])
        elif "board_temp" in status:
            temps = [status.get("board_temp", 0)]
        elif "chip_temp" in status:
            # Some CK-Box firmware reports chip_temp as an array
            chip_temp = status.get("chip_temp", [])
            if isinstance(chip_temp, list):
                temps = chip_temp
            else:
                temps = [chip_temp]
        elif "temperature" in status:
            # Single temperature reading
            temps = [status.get("temperature", 0)]
        
        # Store temps in status for dashboard to access - ALWAYS set it (even if empty)
        data["status"]["temperatures"] = temps
        
        # Also store max temp as a fallback display value
        if temps:
            data["status"]["max_temp"] = max(temps)
            data["status"]["avg_temp"] = sum(temps) / len(temps)
        
        # Extract fan speed if available
        if "fan_speed" in status:
            data["status"]["fan_speed"] = status.get("fan_speed", 0)
        elif "fanSpeed" in status:
            data["status"]["fan_speed"] = status.get("fanSpeed", 0)
    
    # Fetch setting (power plan, temp, LED, MAC)
    setting = fetch_json(ip, "mcb/setting")
    if setting:
        data["setting"] = setting
        data["mac"] = setting.get("name")
    
    # Fetch pools
    pools = fetch_json(ip, "mcb/pools")
    if pools:
        data["pools"] = pools
        
        # Also extract HW errors from pool stats (rejected/stale shares indicate hardware issues)
        # Goldshell reports pool-level shares including invalid/rejected
        pool_list = pools.get("pools", []) if isinstance(pools, dict) else pools
        if isinstance(pool_list, list) and len(pool_list) > 0:
            primary_pool = pool_list[0]
            # Some firmware reports reject_ratio or similar
            if "reject_ratio" in primary_pool:
                data["hw_errors"] = primary_pool.get("reject_ratio", 0)
            elif "rejected" in primary_pool:
                data["hw_errors"] = primary_pool.get("rejected", 0)
    
    # Fetch hashrate history
    hshistory = fetch_json(ip, "cpb/hshistory")
    if hshistory and isinstance(hshistory, list) and len(hshistory) > 0:
        data["hashrate"] = hshistory
        data["current_hashrate"] = hshistory[-1] if hshistory else None
        # Average of last 10 points (~5 minutes)
        data["avg_hashrate"] = sum(hshistory[-10:]) / min(10, len(hshistory)) if hshistory else None
    
    # Log HW errors for debugging
    if data["hw_errors"] > 0:
        logger.info(f"{name} HW errors: {data['hw_errors']}")
    
    return data


def poll_all_miners():
    """Poll all configured miners."""
    global miner_data, miner_history, pool_data
    
    for miner in config.get("miners", []):
        name = miner.get("name", miner["ip"])
        logger.info(f"Polling {name} ({miner['ip']})...")
        
        data = poll_miner(miner)
        
        # Store current data
        miner_data[name] = data
        
        # Track uptime
        # Normalize name to use underscores (consistent with config)
        name = name.replace("-", "_")
        
        if name not in miner_uptime:
            miner_uptime[name] = {"start_time": None, "total_seconds": 0}
        
        current_time = int(time.time())
        
        was_online = miner_uptime[name]["start_time"] is not None
        
        if data["online"]:
            # Only record new start_time if miner was previously offline
            if not was_online:
                miner_uptime[name]["start_time"] = current_time
                logger.info(f"{name} came online")
        else:
            # Miner went offline - accumulate time
            if was_online:
                elapsed = current_time - miner_uptime[name]["start_time"]
                miner_uptime[name]["total_seconds"] += elapsed
                miner_uptime[name]["start_time"] = None
                logger.info(f"{name} went offline after {elapsed}s")
        
        # Append to history (keep last 288 points = 24 hours)
        if name not in miner_history:
            miner_history[name] = []
        
        if data["current_hashrate"]:
            # Use dashboard timestamp for deduplication (always unique per poll)
            entry_ts = datetime.now().isoformat()
            # Skip if we already have an entry with this exact dashboard timestamp
            if not miner_history[name] or miner_history[name][-1]["timestamp"] != entry_ts:
                miner_history[name].append({
                    "timestamp": entry_ts,
                    "hashrate": data["current_hashrate"]
                })
        
        # Trim history
        max_points = config.get("history_points", 288)
        miner_history[name] = miner_history[name][-max_points:]
    
    # Save uptime data periodically
    save_uptime()
    
    # Save history every HISTORY_SAVE_INTERVAL seconds (not every poll)
    global _last_history_save
    if time.time() - _last_history_save > HISTORY_SAVE_INTERVAL:
        save_history()
        _last_history_save = time.time()
    
    # Fetch pool stats
    wallet = config.get("wallet")
    if wallet:
        pool_data["wallet"] = wallet
        stats = fetch_pool_stats(wallet)
        if stats:
            pool_data.update(stats)
            logger.info(f"Pool stats: {stats.get('reward_24h',0):.2f} CKB/24h")
    
    # Fetch pool shares
    if wallet:
        shares = fetch_pool_shares(wallet, "5m")
        if shares:
            pool_data["shares"] = shares
            # Response has valid/stale directly, not under 'shares' key
            valid_count = len(shares.get('valid') or [])
            stale_count = len(shares.get('stale') or [])
            logger.info(f"Pool shares: {valid_count} valid, {stale_count} stale")
    
    # Fetch pool blocks
    blocks = fetch_pool_blocks(wallet)
    if blocks:
        pool_data["blocks"] = blocks
        logger.info(f"Pool blocks: {blocks.get('candidatesTotal', 0)} candidates, {len(blocks.get('immature') or [])} immature")
    
    # Fetch pool payments
    if wallet:
        payments = fetch_pool_payments(wallet)
        if payments:
            pool_data["payments"] = payments
            logger.info(f"Pool payments: {len(payments.get('payments', []))} records")
    
    # Fetch CKB price
    ckb_price = fetch_ckb_price()
    if ckb_price:
        pool_data["ckb_price"] = ckb_price
    
    # Track daily earnings
    track_daily_earnings()
    
    logger.info(f"Poll complete. Online miners: {sum(1 for d in miner_data.values() if d['online'])}")


def background_poll():
    """Background thread to poll miners periodically."""
    while True:
        poll_all_miners()
        time.sleep(config.get("poll_interval", 30))


@app.route('/')
def index():
    """Main dashboard."""
    return render_template('dashboard.html')


@app.route('/api/status')
def api_status():
    # Lazy: fetch pool data if not yet loaded (gunicorn doesn't run main())
    if not pool_data.get("wallet"):
        wallet = config.get("wallet")
        if wallet:
            stats = fetch_pool_stats(wallet)
            if stats:
                pool_data.update(stats)
    
    # Get workers from pool data
    workers = pool_data.get("workers", {})
    
    # Build worker name to miner mapping
    miner_list = config.get("miners", [])
    
    # Calculate combined stats
    combined = {
        "timestamp": datetime.now().isoformat(),
        "total_miners": len(miner_list),
        "online_miners": sum(1 for d in miner_data.values() if d["online"]),
        "miners": []
    }
    
    total_hashrate = 0
    total_avg_hashrate = 0
    
    for i, (name, data) in enumerate(miner_data.items()):
        # Get worker shares from pool (ckbox1, ckbox2, etc.)
        worker_name = f"ckbox{i+1}"
        worker_data = workers.get(worker_name, {})
        
        # Calculate uptime from tracked data (not pool lastBeat)
        ut = miner_uptime.get(name, {"total_seconds": 0, "start_time": None})
        current_uptime = ut.get("total_seconds", 0)
        if ut.get("start_time") and data["online"]:
            current_uptime += int(time.time()) - ut["start_time"]
        
        miner_summary = {
            "name": name,
            "ip": data["ip"],
            "online": data["online"],
            "model": data.get("status", {}).get("model", "Unknown"),
            "firmware": data.get("status", {}).get("firmware", "Unknown"),
            "current_hashrate": int(data.get("current_hashrate", 0) * 1e6) if data.get("current_hashrate") else 0,
            "avg_hashrate": int(data.get("avg_hashrate", 0) * 1e6) if data.get("avg_hashrate") else 0,
            "hw_errors": data.get("hw_errors", 0),
            "pools": data.get("pools", []),
            "setting": data.get("setting", {}),
            "mac": data.get("mac"),
            "last_update": data.get("last_update"),
            "worker_name": worker_name,
            "shares_valid": worker_data.get("sharesValid", 0),
            "shares_stale": worker_data.get("sharesStale", 0),
            "shares_invalid": worker_data.get("sharesInvalid", 0),
            "worker_offline": worker_data.get("offline", False),
            "last_beat": worker_data.get("lastBeat"),
            "uptime_seconds": current_uptime
        }
        combined["miners"].append(miner_summary)
        
        # Use pool workers' hashrate for accurate totals
    # hr = current hashrate in H/s, hr2 = variance * 1e6 in (MH/s)^2
    # avg hashrate = sqrt(hr2) * 1e6 H/s
    workers = pool_data.get("workers", {})
    total_hashrate = sum(w.get("hr", 0) for w in workers.values())
    total_avg_hashrate = sum(sqrt(w.get("hr2", 0)) * 1e6 if w.get("hr2") else w.get("hr", 0) for w in workers.values())
    
    combined["total_current_hashrate"] = total_hashrate
    combined["total_avg_hashrate"] = total_avg_hashrate
    combined["pool"] = pool_data
    
    # Add network stats for calculator-based daily estimate
    try:
        net_resp = requests.get("http://localhost:5000/api/network/current", timeout=5)
        if net_resp.status_code == 200:
            net_data = net_resp.json()
            combined["network_hashrate"] = net_data.get("hash_rate", 0)  # H/s
            combined["network_diff"] = net_data.get("current_difficulty", 0)  # raw difficulty
    except:
        pass
    
    # Get block reward from statistics
    try:
        stats_resp = requests.get("http://localhost:5000/api/statistics", timeout=5)
        if stats_resp.status_code == 200:
            stats_data = stats_resp.json()
            combined["block_reward"] = stats_data.get("block_reward", 0)  # CKB
    except:
        pass
    
    # Calculate combined rejection rate from miner shares
    total_valid = sum(m["shares_valid"] for m in combined["miners"])
    total_stale = sum(m["shares_stale"] for m in combined["miners"])
    total_invalid = sum(m["shares_invalid"] for m in combined["miners"])
    total_shares = total_valid + total_stale + total_invalid
    combined["rejection_rate"] = (total_stale + total_invalid) / total_shares * 100 if total_shares > 0 else 0
    combined["total_shares_valid"] = total_valid
    combined["total_shares_stale"] = total_stale
    combined["total_shares_invalid"] = total_invalid
    
    return jsonify(combined)


@app.route('/api/history')
def api_history():
    """JSON history for charts."""
    return jsonify(miner_history)


@app.route('/api/shares')
def api_shares():
    """JSON shares data from pool."""
    return jsonify(pool_data.get("shares", {}))


@app.route('/api/shares/<interval>')
def api_shares_interval(interval):
    """Fetch shares for specific interval."""
    wallet = config.get("wallet")
    if not wallet:
        return jsonify({"error": "No wallet configured"})
    
    shares = fetch_pool_shares(wallet, interval)
    if shares:
        return jsonify(shares)
    return jsonify({"error": "Failed to fetch shares"})


@app.route('/api/payments')
def api_payments():
    """JSON payments data from pool."""
    payments_data = pool_data.get("payments", {})
    # If no cached data, try fetching fresh
    if not payments_data or not payments_data.get("payments"):
        wallet = config.get("wallet")
        if wallet:
            payments_data = fetch_pool_payments(wallet)
            if payments_data:
                pool_data["payments"] = payments_data
    return jsonify(payments_data)


@app.route('/api/rewards')
def api_rewards():
    """JSON rewards (immature/confirmed blocks) from pool."""
    rewards = pool_data.get("rewards", [])
    return jsonify({"rewards": rewards})


@app.route('/api/blocks')
def api_blocks():
    """JSON blocks data from pool."""
    return jsonify(pool_data.get("blocks", {}))


@app.route('/network')
def network_page():
    """Network Hashrate Dashboard."""
    return render_template('network.html')


@app.route('/api/network/current')
def api_network_current():
    """Get real-time network hashrate and difficulty from statistics API."""
    global _network_current_cache, _network_current_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _network_current_cache is not None and (now - _network_current_fetch_time) < NETWORK_CURRENT_CACHE_SECONDS:
        return jsonify(_network_current_cache)
    
    try:
        headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/statistics", 
                           headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        
        attrs = raw.get("data", {}).get("attributes", {})
        epoch = attrs.get("epoch_info", {})
        
        # Explorer API returns hash_rate in H/s - return raw for formatHashrate() to handle
        # formatHashrate expects H/s: >=1e15 -> PH/s, >=1e12 -> TH/s, >=1e9 -> GH/s, etc.
        raw_hashrate = float(attrs.get("hash_rate", 0))
        
        data = {
            "hash_rate": raw_hashrate,  # Raw H/s - formatHashrate() converts to appropriate unit
            "current_difficulty": float(attrs.get("current_epoch_difficulty", 0)),
            "tip_block": int(attrs.get("tip_block_number", 0)),
            "epoch_number": int(epoch.get("epoch_number", 0)),
            "epoch_progress": f"{epoch.get('index', 0)}/{epoch.get('epoch_length', 0)}",
            "average_block_time_sec": round(float(attrs.get("average_block_time", 0)) / 1000, 2),
            "updated_at": datetime.now().isoformat()
        }
        
        _network_current_cache = data
        _network_current_fetch_time = now
        
        return jsonify(data)
    except Exception as e:
        logger.warning(f"Failed to fetch current network stats: {e}")
        if _network_current_cache is not None:
            return jsonify(_network_current_cache)
        return jsonify({"error": str(e)}), 500


@app.route('/api/network/hashrate')
def api_network_hashrate():
    """Fetch network hashrate from Nervos explorer API (cached, limited to 90 days)."""
    global _network_hashrate_cache, _network_hashrate_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _network_hashrate_cache is not None and (now - _network_hashrate_fetch_time) < NETWORK_HASHRATE_CACHE_SECONDS:
        return jsonify(_network_hashrate_cache)
    
    try:
        headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/daily_statistics/avg_hash_rate", 
                           headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        
        # Parse JSON:API format to simple {date, avgHashRate} format
        data = []
        for item in raw.get("data", []):
            attrs = item.get("attributes", {})
            timestamp = attrs.get("created_at_unixtimestamp")
            hashrate = attrs.get("avg_hash_rate")
            if timestamp and hashrate:
                # Convert Unix timestamp to date string
                date = datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")
                data.append({
                    "date": date,
                    "avgHashRate": float(hashrate)
                })
        
        # Sort by date and limit to last 90 days (3 months of history max)
        data.sort(key=lambda x: x["date"])
        data = data[-90:]  # Only keep last 90 data points
        
        # Cache the result
        _network_hashrate_cache = data
        _network_hashrate_fetch_time = now
        
        logger.info(f"Fetched network hashrate: {len(data)} days cached")
        return jsonify(data)
    except Exception as e:
        logger.warning(f"Failed to fetch network hashrate: {e}")
        # Return stale cache if available, otherwise error
        if _network_hashrate_cache is not None:
            return jsonify(_network_hashrate_cache)
        return jsonify({"error": str(e)}), 500


@app.route('/api/network/difficulty')
def api_network_difficulty():
    """Fetch network difficulty from Nervos explorer API (cached, limited to 90 days)."""
    global _network_difficulty_cache, _network_difficulty_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _network_difficulty_cache is not None and (now - _network_difficulty_fetch_time) < NETWORK_DIFFICULTY_CACHE_SECONDS:
        return jsonify(_network_difficulty_cache)
    
    try:
        headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/daily_statistics/avg_difficulty", 
                           headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        
        # Parse JSON:API format to simple {date, avgDifficulty} format
        data = []
        for item in raw.get("data", []):
            attrs = item.get("attributes", {})
            timestamp = attrs.get("created_at_unixtimestamp")
            difficulty = attrs.get("avg_difficulty")
            if timestamp and difficulty:
                # Convert Unix timestamp to date string
                date = datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")
                data.append({
                    "date": date,
                    "avgDifficulty": float(difficulty)
                })
        
        # Sort by date and limit to last 90 days (3 months of history max)
        data.sort(key=lambda x: x["date"])
        data = data[-90:]  # Only keep last 90 data points
        
        # Cache the result
        _network_difficulty_cache = data
        _network_difficulty_fetch_time = now
        
        logger.info(f"Fetched network difficulty: {len(data)} days cached")
        return jsonify(data)
    except Exception as e:
        logger.warning(f"Failed to fetch network difficulty: {e}")
        # Return stale cache if available, otherwise error
        if _network_difficulty_cache is not None:
            return jsonify(_network_difficulty_cache)
        return jsonify({"error": str(e)}), 500


# Market data cache
_market_data_cache = None
_market_data_fetch_time = 0
MARKET_DATA_CACHE_SECONDS = 300  # Cache for 5 minutes

# Price history cache
_price_history_cache = None
_price_history_fetch_time = 0
PRICE_HISTORY_CACHE_SECONDS = 3600  # Cache for 1 hour

# Transactions cache
_transactions_cache = None
_transactions_fetch_time = 0
TRANSACTIONS_CACHE_SECONDS = 60  # Cache for 1 minute

# Blocks cache
_blocks_cache = None
_blocks_fetch_time = 0
BLOCKS_CACHE_SECONDS = 60  # Cache for 1 minute

# Statistics cache
_statistics_cache = None
_statistics_fetch_time = 0
STATISTICS_CACHE_SECONDS = 60  # Cache for 1 minute


def fetch_ckb_price_history(days=30):
    """Fetch CKB price history from CoinGecko API."""
    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/nervos-network/market_chart?vs_currency=usd&days={days}",
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        
        # Process prices - data is [timestamp, price]
        prices = []
        for item in data.get("prices", []):
            timestamp = item[0]  # milliseconds
            price = item[1]
            date = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d")
            prices.append({
                "date": date,
                "timestamp": timestamp,
                "price": float(price)
            })
        
        # Sample to reduce data points (keep every 6th point for cleaner chart)
        sampled = prices[::6] if len(prices) > 100 else prices
        
        return sampled
    except Exception as e:
        logger.warning(f"Failed to fetch CKB price history: {e}")
        return None


@app.route('/market')
def market_page():
    """Market Data page."""
    return render_template('market.html')


@app.route('/transactions')
def transactions_page():
    """Transactions page."""
    return render_template('transactions.html')


@app.route('/blocks')
def blocks_page():
    """Blocks page."""
    return render_template('blocks.html')


@app.route('/payments')
def payments_page():
    """Payments page."""
    return render_template('payments.html')


@app.route('/calculator')
def calculator_page():
    """Mining Calculator page."""
    return render_template('calculator.html')



@app.route('/statistics')
def statistics_page():
    """Statistics page."""
    return render_template('statistics.html')


@app.route('/api/market/data')
def api_market_data():
    """Fetch market data from Nervos explorer API (cached)."""
    global _market_data_cache, _market_data_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _market_data_cache is not None and (now - _market_data_fetch_time) < MARKET_DATA_CACHE_SECONDS:
        return jsonify(_market_data_cache)
    
    try:
        headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/market_data", 
                           headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        
        # Get CKB price (already have fetch_ckb_price function)
        ckb_price = fetch_ckb_price() or 0
        
        # Combine market data with price
        data = {
            "total_supply": float(raw.get("total_supply", 0)),
            "circulating_supply": float(raw.get("circulating_supply", 0)),
            "ckb_price_usd": ckb_price,
            "market_cap": float(raw.get("circulating_supply", 0)) * ckb_price,
            "updated_at": datetime.now().isoformat()
        }
        
        # Cache the result
        _market_data_cache = data
        _market_data_fetch_time = now
        
        logger.info(f"Fetched market data: supply={data['circulating_supply']/1e9:.2f}B, price=${ckb_price:.4f}")
        return jsonify(data)
    except Exception as e:
        logger.warning(f"Failed to fetch market data: {e}")
        # Return stale cache if available, otherwise error
        if _market_data_cache is not None:
            return jsonify(_market_data_cache)
        return jsonify({"error": str(e)}), 500


@app.route('/api/market/price_history')
def api_market_price_history():
    """Fetch CKB price history from CoinGecko API (cached)."""
    global _price_history_cache, _price_history_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _price_history_cache is not None and (now - _price_history_fetch_time) < PRICE_HISTORY_CACHE_SECONDS:
        return jsonify(_price_history_cache)
    
    try:
        data = fetch_ckb_price_history(days=30)
        
        if data:
            _price_history_cache = data
            _price_history_fetch_time = now
            logger.info(f"Fetched price history: {len(data)} points")
            return jsonify(data)
        else:
            # Return stale cache if available
            if _price_history_cache is not None:
                return jsonify(_price_history_cache)
            return jsonify({"error": "Failed to fetch price history"}), 500
            
    except Exception as e:
        logger.warning(f"Failed to fetch price history: {e}")
        # Return stale cache if available
        if _price_history_cache is not None:
            return jsonify(_price_history_cache)
        return jsonify({"error": str(e)}), 500


@app.route('/api/transactions')
def api_transactions():
    """Fetch recent transactions from Nervos explorer API (cached)."""
    global _transactions_cache, _transactions_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _transactions_cache is not None and (now - _transactions_fetch_time) < TRANSACTIONS_CACHE_SECONDS:
        return jsonify(_transactions_cache)
    
    try:
        headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/transactions?limit=50", 
                           headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        
        # Parse transactions
        transactions = []
        for item in raw.get("data", []):
            attrs = item.get("attributes", {})
            tx_hash = attrs.get("transaction_hash", "")
            block_num = attrs.get("block_number", 0)
            timestamp = attrs.get("block_timestamp", 0)
            capacity = attrs.get("capacity_involved", 0)
            
            # Convert timestamp from milliseconds to datetime
            if timestamp:
                tx_time = datetime.fromtimestamp(int(timestamp) / 1000)
            else:
                tx_time = datetime.now()
            
            transactions.append({
                "tx_hash": tx_hash,
                "tx_hash_short": tx_hash[:20] + "..." if len(tx_hash) > 20 else tx_hash,
                "block_number": block_num,
                "timestamp": tx_time.isoformat(),
                "time_ago": (datetime.now() - tx_time).total_seconds(),
                "capacity_ckb": float(capacity) / 1e8 if capacity else 0,  # Convert from shannons to CKB
                "capacity_formatted": f"{float(capacity) / 1e8:.2f}" if capacity else "0.00"
            })
        
        data = {
            "transactions": transactions,
            "count": len(transactions),
            "updated_at": datetime.now().isoformat()
        }
        
        # Cache the result
        _transactions_cache = data
        _transactions_fetch_time = now
        
        logger.info(f"Fetched {len(transactions)} transactions")
        return jsonify(data)
    except Exception as e:
        logger.warning(f"Failed to fetch transactions: {e}")
        # Return stale cache if available, otherwise error
        if _transactions_cache is not None:
            return jsonify(_transactions_cache)
        return jsonify({"error": str(e)}), 500


@app.route('/api/ckb_blocks')
def api_ckb_blocks():
    """Fetch recent blocks from Nervos explorer API (cached)."""
    global _blocks_cache, _blocks_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _blocks_cache is not None and (now - _blocks_fetch_time) < BLOCKS_CACHE_SECONDS:
        return jsonify(_blocks_cache)
    
    try:
        headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/blocks?limit=50", 
                           headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        
        # Parse blocks
        blocks = []
        for item in raw.get("data", []):
            attrs = item.get("attributes", {})
            block_num = int(attrs.get("number", 0))
            miner = attrs.get("miner_hash", "")
            timestamp = attrs.get("timestamp", 0)
            reward = attrs.get("reward", 0)
            tx_count = attrs.get("transactions_count", 0)
            
            # Convert timestamp from milliseconds to datetime
            if timestamp:
                block_time = datetime.fromtimestamp(int(timestamp) / 1000)
            else:
                block_time = datetime.now()
            
            blocks.append({
                "block_number": block_num,
                "miner_hash": miner,
                "miner_short": miner[:20] + "..." if len(miner) > 20 else miner,
                "timestamp": block_time.isoformat(),
                "time_ago": (datetime.now() - block_time).total_seconds(),
                "reward_ckb": float(reward) / 1e8 if reward else 0,
                "reward_formatted": f"{float(reward) / 1e8:.3f}" if reward else "0.000",
                "transactions_count": tx_count
            })
        
        data = {
            "blocks": blocks,
            "count": len(blocks),
            "updated_at": datetime.now().isoformat()
        }
        
        # Cache the result
        _blocks_cache = data
        _blocks_fetch_time = now
        
        logger.info(f"Fetched {len(blocks)} blocks")
        return jsonify(data)
    except Exception as e:
        logger.warning(f"Failed to fetch blocks: {e}")
        # Return stale cache if available, otherwise error
        if _blocks_cache is not None:
            return jsonify(_blocks_cache)
        return jsonify({"error": str(e)}), 500


@app.route('/api/statistics')
def api_statistics():
    """Fetch network statistics from Nervos explorer API (cached)."""
    global _statistics_cache, _statistics_fetch_time
    
    # Return cached data if fresh
    now = time.time()
    if _statistics_cache is not None and (now - _statistics_fetch_time) < STATISTICS_CACHE_SECONDS:
        return jsonify(_statistics_cache)
    
    try:
        headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/statistics", 
                           headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        
        attrs = raw.get("data", {}).get("attributes", {})
        epoch = attrs.get("epoch_info", {})
        
        # Fetch recent blocks to calculate actual block reward
        # The explorer statistics endpoint returns 0 for block_reward
        block_reward = 0
        try:
            blocks_resp = requests.get("https://mainnet-api.explorer.nervos.org/api/v1/blocks?limit=10", 
                                      headers=headers, timeout=10)
            blocks_raw = blocks_resp.json()
            rewards = []
            for item in blocks_raw.get("data", [])[:5]:  # Use last 5 blocks
                reward = item.get("attributes", {}).get("reward", 0)
                if reward:
                    rewards.append(float(reward) / 1e8)  # Convert from shannons to CKB
            if rewards:
                block_reward = sum(rewards) / len(rewards)
        except Exception as e:
            logger.warning(f"Failed to fetch block reward from blocks: {e}")
        
        # Calculate epoch time remaining (not total)
        epoch_index = int(epoch.get("index", 0))
        epoch_length = int(epoch.get("epoch_length", 0))
        total_epoch_time_ms = float(attrs.get("estimated_epoch_time", 0))
        avg_block_time_ms = float(attrs.get("average_block_time", 0))
        
        # Remaining blocks = epoch_length - epoch_index - 1 (0-indexed)
        remaining_blocks = max(0, epoch_length - epoch_index - 1)
        # Remaining time = remaining blocks * avg block time
        if remaining_blocks > 0 and avg_block_time_ms > 0:
            remaining_time_ms = remaining_blocks * avg_block_time_ms
        else:
            remaining_time_ms = 0
        remaining_time_hours = round(remaining_time_ms / 3600000, 2)
        remaining_time_min = round(remaining_time_ms / 60000, 1)
        
        data = {
            "tip_block": int(attrs.get("tip_block_number", 0)),
            "epoch_number": int(epoch.get("epoch_number", 0)),
            "epoch_index": epoch_index,
            "epoch_length": epoch_length,
            "epoch_progress": f"{epoch.get('index', 0)}/{epoch.get('epoch_length', 0)}",
            "average_block_time_ms": avg_block_time_ms,
            "average_block_time_sec": round(avg_block_time_ms / 1000, 2),
            "current_difficulty": float(attrs.get("current_epoch_difficulty", 0)),
            "hash_rate": float(attrs.get("hash_rate", 0)),
            "total_epoch_time_hours": round(total_epoch_time_ms / 3600000, 2),
            "estimated_epoch_time_remaining_ms": remaining_time_ms,
            "estimated_epoch_time_remaining_hours": remaining_time_hours,
            "estimated_epoch_time_remaining_min": remaining_time_min,
            "transactions_24h": int(attrs.get("transactions_last_24hrs", 0)),
            "tx_per_minute": float(attrs.get("transactions_count_per_minute", 0)),
            "block_reward": block_reward,
            "updated_at": datetime.now().isoformat()
        }
        
        # Cache the result
        _statistics_cache = data
        _statistics_fetch_time = now
        
        logger.info(f"Fetched statistics: epoch={data['epoch_number']}, tx_24h={data['transactions_24h']}, block_reward={block_reward:.1f} CKB")
        return jsonify(data)
    except Exception as e:
        logger.warning(f"Failed to fetch statistics: {e}")
        # Return stale cache if available, otherwise error
        if _statistics_cache is not None:
            return jsonify(_statistics_cache)
        return jsonify({"error": str(e)}), 500


@app.route('/api/earnings')
def api_earnings():
    """JSON earnings history."""
    return jsonify(earnings_history)


@app.route('/api/config')
def api_config():
    """Get/set configuration."""
    if request.method == 'POST':
        new_config = request.json
        config.update(new_config)
        save_config()
        return jsonify({"status": "ok"})
    return jsonify(config)


@app.route('/api/miners', methods=['PUT'])
def api_update_miners():
    """Update miners list from mobile app."""
    global config
    data = request.json or {}
    miners = data.get('miners', [])
    wallet = data.get('wallet')
    poll_interval = data.get('poll_interval')

    if miners:
        config['miners'] = miners
    if wallet:
        config['wallet'] = wallet
    if poll_interval:
        config['poll_interval'] = poll_interval

    save_config()
    return jsonify({"status": "ok", "miners": config.get('miners', [])})


@app.route('/api/uptime/reset/<miner_name>')
def api_reset_uptime(miner_name):
    """Reset uptime for a specific miner."""
    global miner_uptime
    
    # Normalize name
    key = miner_name.replace("-", "_")
    
    if key in miner_uptime:
        miner_uptime[key] = {"start_time": int(time.time()), "total_seconds": 0}
        save_uptime()
        return jsonify({"status": "ok", "miner": miner_name, "uptime_reset": True})
    return jsonify({"status": "error", "miner": miner_name, "not_found": True})


def main():
    load_config()
    load_uptime()
    load_earnings_history()
    load_history()
    
    # Initial poll
    poll_all_miners()
    
    # Start background polling
    poll_thread = threading.Thread(target=background_poll, daemon=True)
    poll_thread.start()
    
    # Check for templates folder
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    
    # Check if dashboard exists, create default if not
    dashboard_path = templates_dir / "dashboard.html"
    if not dashboard_path.exists():
        logger.info("Creating default dashboard template...")
    
    logger.info("Starting Miner Monitor Dashboard on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)


if __name__ == "__main__":
    main()

