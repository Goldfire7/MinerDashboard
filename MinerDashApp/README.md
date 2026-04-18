# MinerDash App

Mobile APK for monitoring your Goldshell CK-Box miners.

## First-Launch Setup Wizard

On first launch, the app guides you through 3 steps:

1. **Pool Settings** — pool URL + CKB wallet address
2. **Server / Miner IPs** — your MinerMonitor server URL + individual miner IPs
3. **Confirm** — review and launch

Settings are saved locally on the device and synced to your Flask backend.

## Architecture

```
┌─────────────────┐         ┌──────────────────────────────┐
│  Mobile APK     │ ──────► │  MinerMonitor Flask Server   │
│  (Vue + Capacitor)         │  (your current dashboard)   │
│  MinerDash-v1   │ ◄────── │  polling miners + 2miners   │
└─────────────────┘   API   └──────────────────────────────┘
```

The APK does **not** poll miners directly — it talks to your existing Flask backend (`http://YOUR_SERVER:5000`).

## APK Location

```
MinerDashApp/MinerDash-v1.0.0.apk
```

Install on Android device, enter your server IP (e.g. `http://192.168.0.x:5000`), done.

## MinerMonitor Server

Your Flask server must be running for the app to work:

```bash
cd ~/.openclaw/workspace/MinerDashboard
python3 miner_monitor.py
```

The app syncs miner IPs to the backend via `PUT /api/miners`.

## Rebuild APK

Requires Android SDK:

```bash
cd MinerDashApp
npm run cap:build
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`