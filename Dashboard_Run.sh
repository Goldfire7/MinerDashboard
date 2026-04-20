#!/bin/bash
cd "$(dirname "$0")"
nohup python3 miner_monitor.py > /dev/null 2>&1 &
echo "MinerDashboard started"
