<template>
  <div class="app">
    <!-- Setup Wizard -->
    <div v-if="!isConfigured" class="wizard">
      <div class="wizard-header">
        <h1>⚡ CK-Box Miner</h1>
        <p>Configure your mining setup</p>
      </div>

      <div class="wizard-step" v-if="step === 1">
        <h2>Step 1: Pool Settings</h2>
        <div class="field">
          <label>Pool URL</label>
          <input v-model="config.poolUrl" placeholder="https://ckb.2miners.com" />
          <span class="hint">Your mining pool homepage</span>
        </div>
        <div class="field">
          <label>Wallet Address</label>
          <input v-model="config.wallet" placeholder="ckb1qy..." />
          <span class="hint">Your CKB wallet address</span>
        </div>
      </div>

      <div class="wizard-step" v-if="step === 2">
        <h2>Step 2: Miner IPs</h2>
        <div class="field">
          <label>Server / API URL</label>
          <input v-model="config.serverUrl" placeholder="http://192.168.0.100:5000" />
          <span class="hint">Your MinerMonitor server URL (include port)</span>
        </div>
        <div class="miner-list">
          <div class="miner-entry" v-for="(miner, i) in config.miners" :key="i">
            <span class="miner-name">{{ miner.name }}</span>
            <input v-model="miner.ip" placeholder="192.168.0.x" />
          </div>
        </div>
      </div>

      <div class="wizard-step" v-if="step === 3">
        <h2>Step 3: Confirm</h2>
        <div class="confirm-box">
          <div class="confirm-item"><span>Pool:</span> {{ config.poolUrl }}</div>
          <div class="confirm-item"><span>Wallet:</span> {{ config.wallet }}</div>
          <div class="confirm-item"><span>Server:</span> {{ config.serverUrl }}</div>
          <div class="confirm-item"><span>Miners:</span>
            <div v-for="m in config.miners" :key="m.name">{{ m.name }} → {{ m.ip || 'not set' }}</div>
          </div>
        </div>
        <p class="save-note">Settings saved locally on device.</p>
      </div>

      <div class="wizard-footer">
        <button v-if="step > 1" @click="step--" class="btn-back">← Back</button>
        <div class="spacer"></div>
        <button v-if="step < 3" @click="nextStep" class="btn-next">Next →</button>
        <button v-if="step === 3" @click="saveConfig" class="btn-save">✓ Launch Dashboard</button>
      </div>

      <div class="step-dots">
        <span v-for="s in 3" :key="s" :class="{ active: s === step }"></span>
      </div>
    </div>

    <!-- Dashboard -->
    <div v-else class="dashboard">
      <header>
        <div class="header-left">
          <div class="header-card">
            <div class="label">⚡ CKB Miner</div>
            <div class="links">
              <a :href="config.poolUrl" target="_blank">Pool ↗</a>
              <a href="https://explorer.nervos.org" target="_blank">Explorer ↗</a>
            </div>
          </div>
        </div>
        <div class="header-center">
          <div class="header-card main-title">
            <div class="label">CK-Box Dashboard</div>
            <div class="online-count">{{ onlineCount }}/{{ minerCount }} Online</div>
          </div>
        </div>
        <div class="header-right">
          <div class="header-card">
            <div class="label">⚙️ Settings</div>
            <button @click="resetConfig" class="settings-btn">Reconfigure</button>
          </div>
        </div>
      </header>

      <!-- Stats Bar -->
      <div class="stats-bar">
        <div class="stat-chip">
          <span class="chip-label">Total Hashrate</span>
          <span class="chip-value">{{ formatHashrate(totalHashrate) }}</span>
        </div>
        <div class="stat-chip">
          <span class="chip-label">24h Reward</span>
          <span class="chip-value">{{ poolData.reward_24h || 0 | fixed(2) }} CKB</span>
        </div>
        <div class="stat-chip">
          <span class="chip-label">Price</span>
          <span class="chip-value">${{ poolData.ckb_price || 0 | fixed(4) }}</span>
        </div>
        <div class="stat-chip">
          <span class="chip-label">Luck</span>
          <span class="chip-value">{{ poolData.luck || 0 | fixed(0) }}%</span>
        </div>
      </div>

      <!-- Miner Cards -->
      <div class="miner-grid">
        <div v-for="miner in miners" :key="miner.name"
          class="miner-card" :class="{ offline: !miner.online }">
          <div class="miner-name">{{ miner.name }}</div>
          <div class="miner-ip">{{ miner.ip }}</div>
          <div class="miner-hashrate">
            <span class="big-num">{{ formatHashrate(miner.current_hashrate) }}</span>
            <span class="sub-hash">Avg: {{ formatHashrate(miner.avg_hashrate) }}</span>
          </div>
          <div class="miner-meta">
            <div class="meta-row">
              <span class="meta-label">Uptime</span>
              <span class="meta-val">{{ formatUptime(miner.uptime_seconds) }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">Shares</span>
              <span class="meta-val good">{{ miner.shares_valid || 0 }}/{{ (miner.shares_valid || 0) + (miner.shares_stale || 0) }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">Errors</span>
              <span class="meta-val" :class="{ warn: miner.hw_errors > 0 }">{{ miner.hw_errors }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Blocks -->
      <div class="section">
        <h2>Recent Blocks</h2>
        <div class="blocks-list">
          <div v-if="!blocks.length" class="empty">No blocks yet</div>
          <div v-for="block in blocks.slice(0, 10)" :key="block.timestamp"
            class="block-row" :class="{ immature: block.immature, orphan: block.orphan }">
            <span class="block-reward">{{ (block.reward / 1e8) | fixed(2) }} CKB</span>
            <span class="block-status">
              {{ block.orphan ? '⬜ Orphan' : block.immature ? '🟡 Immature' : '🟢 Confirmed' }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import './style.css'

const STORAGE_KEY = 'miner_dash_config'

export default {
  filters: {
    fixed(val, decimals) {
      return parseFloat(val || 0).toFixed(decimals)
    }
  },
  data() {
    return {
      isConfigured: false,
      step: 1,
      config: {
        poolUrl: 'https://ckb.2miners.com',
        wallet: '',
        serverUrl: 'http://localhost:5000',
        miners: [
          { name: 'CK_Box_1', ip: '' },
          { name: 'CK_Box_2', ip: '' },
          { name: 'CK_Box_3', ip: '' },
          { name: 'CK_Box_4', ip: '' }
        ]
      },
      minerData: [],
      poolData: {},
      blocks: [],
      pollInterval: null
    }
  },
  computed: {
    miners() { return this.minerData },
    minerCount() { return this.config.miners.length },
    onlineCount() { return this.minerData.filter(m => m.online).length },
    totalHashrate() {
      return this.minerData.filter(m => m.online)
        .reduce((s, m) => s + (m.current_hashrate || 0), 0)
    },
    blocksData() { return this.blocks }
  },
  async mounted() {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const cfg = JSON.parse(saved)
        this.config = cfg
        this.isConfigured = true
        this.startPolling()
      } catch { }
    }
  },
  beforeDestroy() {
    if (this.pollInterval) clearInterval(this.pollInterval)
  },
  methods: {
    nextStep() {
      if (this.step === 1 && (!this.config.wallet || !this.config.poolUrl)) {
        alert('Please fill in pool URL and wallet address')
        return
      }
      this.step++
    },
    async saveConfig() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.config))
      // Sync miners + wallet to Flask backend
      try {
        await fetch(`${this.config.serverUrl}/api/miners`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            miners: this.config.miners,
            wallet: this.config.wallet
          })
        })
      } catch (e) {
        console.warn('Could not sync config to server:', e)
      }
      this.isConfigured = true
      this.startPolling()
    },
    resetConfig() {
      localStorage.removeItem(STORAGE_KEY)
      this.isConfigured = false
      this.step = 1
      this.config = {
        poolUrl: 'https://ckb.2miners.com',
        wallet: '',
        serverUrl: 'http://localhost:5000',
        miners: [
          { name: 'CK_Box_1', ip: '' },
          { name: 'CK_Box_2', ip: '' },
          { name: 'CK_Box_3', ip: '' },
          { name: 'CK_Box_4', ip: '' }
        ]
      }
    },
    startPolling() {
      this.poll()
      this.pollInterval = setInterval(() => this.poll(), 5000)
    },
    async poll() {
      try {
        const r = await fetch(`${this.config.serverUrl}/api/status`)
        const data = await r.json()
        this.minerData = data.miners || []
        this.poolData = data.pool || {}
        const blocksR = await fetch(`${this.config.serverUrl}/api/blocks`)
        const blocksData = await blocksR.json()
        this.blocks = blocksData.immature || []
      } catch (e) {
        console.warn('Poll failed:', e)
      }
    },
    formatHashrate(h) {
      if (!h) return '0 H/s'
      if (h >= 1e12) return (h / 1e12).toFixed(2) + ' TH/s'
      if (h >= 1e9) return (h / 1e9).toFixed(2) + ' GH/s'
      if (h >= 1e6) return (h / 1e6).toFixed(2) + ' MH/s'
      return h.toFixed(0) + ' H/s'
    },
    formatUptime(seconds) {
      if (!seconds) return '--'
      const h = Math.floor(seconds / 3600)
      const m = Math.floor((seconds % 3600) / 60)
      return h > 0 ? `${h}h ${m}m` : `${m}m`
    }
  }
}
</script>