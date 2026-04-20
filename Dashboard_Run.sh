#!/bin/bash
cd /home/dalton/.openclaw/workspace/MinerDashboard
nohup python3 miner_monitor.py > /dev/null 2>&1 &
echo "MinerDashboard started on http://192.168.0.57:5000"
