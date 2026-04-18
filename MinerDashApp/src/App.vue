<template>
  <div class="app">

    <!-- ═══════════════ SETUP WIZARD ═══════════════ -->
    <div v-if="!isConfigured" class="wizard">
      <div class="wizard-header">
        <h1>⚡ MinerDash</h1>
        <p>Monitor your mining rigs</p>
      </div>

      <!-- Step 1: Coin + Pool + Wallet -->
      <div class="wizard-step" v-if="step === 1">
        <h2>Step 1: Coin &amp; Wallet</h2>

        <!-- Coin selector -->
        <div class="field">
          <label>Select Coin</label>
          <div class="coin-grid">
            <button
              v-for="coin in coins"
              :key="coin.ticker"
              class="coin-btn"
              :class="{ active: config.coin === coin.ticker }"
              @click="selectCoin(coin)"
              type="button"
            >
              <span class="coin-icon">{{ coin.icon }}</span>
              <span class="coin-name">{{ coin.name }}</span>
              <span class="coin-ticker">{{ coin.ticker }}</span>
            </button>
          </div>
        </div>

        <div class="field">
          <label>Pool URL</label>
          <input v-model="config.poolUrl" :placeholder="poolPlaceholder" />
          <span class="hint">{{ poolHint }}</span>
        </div>

        <div class="field">
          <label>Wallet Address</label>
          <input v-model="config.wallet" :placeholder="walletPlaceholder" />
          <span class="hint">{{ walletHint }}</span>
        </div>
      </div>

      <!-- Step 2: Server + Miner count + Miner IPs -->
      <div class="wizard-step" v-if="step === 2">
        <h2>Step 2: Server &amp; Miners</h2>

        <div class="field">
          <label>Server / API URL</label>
          <input v-model="config.serverUrl" placeholder="http://192.168.0.100:5000" />
          <span class="hint">MinerMonitor server URL (include port)</span>
        </div>

        <div class="field">
          <label>How many miners?</label>
          <div class="miner-count-row">
            <button @click="changeMinerCount(-1)" type="button" class="count-btn">−</button>
            <span class="count-display">{{ config.minerCount }}</span>
            <button @click="changeMinerCount(1)" type="button" class="count-btn">+</button>
          </div>
        </div>

        <div class="miner-list">
          <div class="miner-entry" v-for="(miner, i) in config.miners" :key="i">
            <input v-model="miner.name" class="miner-name-input" placeholder="Miner name" />
            <span class="arrow">→</span>
            <input v-model="miner.ip" placeholder="IP address" />
          </div>
        </div>
      </div>

      <!-- Step 3: Confirm -->
      <div class="wizard-step" v-if="step === 3">
        <h2>Step 3: Confirm</h2>
        <div class="confirm-box">
          <div class="confirm-item">
            <span>Coin</span>
            {{ coinName }} ({{ config.coin }})
          </div>
          <div class="confirm-item">
            <span>Pool</span> {{ config.poolUrl }}
          </div>
          <div class="confirm-item">
            <span>Wallet</span>
            <span class="wallet-short">{{ config.wallet }}</span>
          </div>
          <div class="confirm-item">
            <span>Server</span> {{ config.serverUrl }}
          </div>
          <div class="confirm-item">
            <span>Miners</span>
            <div v-for="m in config.miners" :key="m.name" class="miner-confirm">
              {{ m.name || 'Unnamed' }} → {{ m.ip || 'no IP' }}
            </div>
          </div>
        </div>
        <p class="save-note">Settings saved locally on your device.</p>
      </div>

      <!-- Navigation -->
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

    <!-- ═══════════════ DASHBOARD ═══════════════ -->
    <div v-else class="dashboard">

      <header>
        <div class="header-left">
          <div class="header-card">
            <div class="label">{{ coinName }} Miner</div>
            <div class="links">
              <a :href="config.poolUrl" target="_blank">Pool ↗</a>
              <a :href="config.explorerUrl" target="_blank">Explorer ↗</a>
            </div>
          </div>
        </div>
        <div class="header-center">
          <div class="header-card main-title">
            <div class="label">⚡ MinerDash</div>
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

      <!-- Stats bar -->
      <div class="stats-bar">
        <div class="stat-chip">
          <span class="chip-label">Total Hashrate</span>
          <span class="chip-value">{{ formatHashrate(totalHashrate) }}</span>
        </div>
        <div class="stat-chip">
          <span class="chip-label">24h Reward</span>
          <span class="chip-value">{{ formatReward(poolData.reward_24h) }} {{ config.coin }}</span>
        </div>
        <div class="stat-chip">
          <span class="chip-label">Price</span>
          <span class="chip-value">{{ poolData.ckb_price ? '$' + poolData.ckb_price.toFixed(4) : '--' }}</span>
        </div>
        <div class="stat-chip">
          <span class="chip-label">Luck</span>
          <span class="chip-value">{{ poolData.luck || 0 | fixed(0) }}%</span>
        </div>
      </div>

      <!-- Miner cards -->
      <div class="miner-grid">
        <div
          v-for="miner in miners"
          :key="miner.name"
          class="miner-card"
          :class="{ offline: !miner.online }"
        >
          <div class="miner-name-row">
            <span class="miner-name">{{ miner.name || 'Unknown' }}</span>
            <span class="online-dot" :class="{ on: miner.online }"></span>
          </div>
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
              <span class="meta-val good">
                {{ miner.shares_valid || 0 }}/
                {{ (miner.shares_valid || 0) + (miner.shares_stale || 0) }}
              </span>
            </div>
            <div class="meta-row">
              <span class="meta-label">Errors</span>
              <span class="meta-val" :class="{ warn: miner.hw_errors > 0 }">
                {{ miner.hw_errors || 0 }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Blocks -->
      <div class="section" v-if="blocks.length">
        <h2>Recent Blocks</h2>
        <div class="blocks-list">
          <div
            v-for="(block, i) in blocks.slice(0, 10)"
            :key="i"
            class="block-row"
            :class="{ immature: block.immature, orphan: block.orphan }"
          >
            <span class="block-reward">{{ formatReward(block.reward) }} {{ config.coin }}</span>
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

const COINS = [
  {
    ticker: 'CKB',
    name: 'Nervos CKB',
    icon: '🔴',
    poolUrl: 'https://ckb.2miners.com',
    explorerUrl: 'https://explorer.nervos.org',
    walletHint: 'ckb1qy...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'DOGE',
    name: 'Dogecoin',
    icon: '🐕',
    poolUrl: 'https://doge.2miners.com',
    explorerUrl: 'https://dogechain.info',
    walletHint: 'D7SS...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'LTC',
    name: 'Litecoin',
    icon: ' LTC',
    poolUrl: 'https://ltc.2miners.com',
    explorerUrl: 'https://blockchair.com/litecoin',
    walletHint: 'LTC...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'ETH',
    name: 'Ethereum',
    icon: 'Ξ',
    poolUrl: 'https://ethermine.org',
    explorerUrl: 'https://etherscan.io',
    walletHint: '0x...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'ETC',
    name: 'Ethereum Classic',
    icon: 'Ξ',
    poolUrl: 'https://etc.ethermine.org',
    explorerUrl: 'https://blockscout.com/etc/mainnet',
    walletHint: '0x...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'RVN',
    name: 'Ravencoin',
    icon: '🌲',
    poolUrl: 'https://rvn.2miners.com',
    explorerUrl: 'https://blockchair.com/ravencoin',
    walletHint: 'RN...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'CFX',
    name: 'Conflux',
    icon: 'CFX',
    poolUrl: 'https://cfx.2miners.com',
    explorerUrl: 'https://confluxscan.io',
    walletHint: 'cfx:...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'ALPH',
    name: 'Alephium',
    icon: 'α',
    poolUrl: 'https://alephium.2miners.com',
    explorerUrl: 'https://explorer.alephium.org',
    walletHint: '...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'SIA',
    name: 'Sia',
    icon: '◇',
    poolUrl: 'https://sia.2miners.com',
    explorerUrl: 'https://siastats.info',
    walletHint: '...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'CTXC',
    name: 'Cortex',
    icon: '█',
    poolUrl: 'https://ctxc.2miners.com',
    explorerUrl: 'https://explorer.cortexlabs.ai',
    walletHint: '0x...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'KAS',
    name: 'Kaspa',
    icon: 'K',
    poolUrl: 'https://kas.2miners.com',
    explorerUrl: 'https://explorer.kaspa.org',
    walletHint: 'kaspa:...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'SOL',
    name: 'Solana',
    icon: '◎',
    poolUrl: 'https://sol.2miners.com',
    explorerUrl: 'https://explorer.solana.com',
    walletHint: '...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'RARE',
    name: 'Aleo',
    icon: 'λ',
    poolUrl: 'https://ale.2miners.com',
    explorerUrl: 'https://explorer.aleo.org',
    walletHint: '...',
    poolHint: 'Pool homepage URL'
  },
  {
    ticker: 'CUSTOM',
    name: 'Custom Coin',
    icon: '⚙️',
    poolUrl: '',
    explorerUrl: '',
    walletHint: 'Your wallet address',
    poolHint: 'Pool homepage URL'
  }
]

function makeMiners(count) {
  return Array.from({ length: count }, (_, i) => ({ name: `Miner ${i + 1}`, ip: '' }))
}

function defaultConfig() {
  return {
    coin: 'CKB',
    poolUrl: 'https://ckb.2miners.com',
    explorerUrl: 'https://explorer.nervos.org',
    wallet: '',
    serverUrl: 'http://localhost:5000',
    minerCount: 4,
    miners: makeMiners(4)
  }
}

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
      coins: COINS,
      config: defaultConfig(),
      minerData: [],
      poolData: {},
      blocks: [],
      pollInterval: null
    }
  },

  computed: {
    miners() { return this.minerData },
    minerCount() { return this.config.minerCount },
    onlineCount() { return this.minerData.filter(m => m.online).length },
    totalHashrate() {
      return this.minerData.filter(m => m.online)
        .reduce((s, m) => s + (m.current_hashrate || 0), 0)
    },
    coinName() {
      return this.coins.find(c => c.ticker === this.config.coin)?.name || this.config.coin
    },
    poolPlaceholder() {
      return this.coins.find(c => c.ticker === this.config.coin)?.poolUrl || 'https://pool.example.com'
    },
    poolHint() {
      return this.coins.find(c => c.ticker === this.config.coin)?.poolHint || 'Pool homepage URL'
    },
    walletPlaceholder() {
      return this.coins.find(c => c.ticker === this.config.coin)?.walletHint || 'Your wallet address'
    },
    walletHint() {
      return 'Your ' + (this.config.coin === 'CUSTOM' ? 'coin' : this.config.coin) + ' wallet address'
    }
  },

  async mounted() {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const cfg = JSON.parse(saved)
        // Upgrade legacy config (no minerCount)
        if (cfg.minerCount === undefined) {
          cfg.minerCount = cfg.miners?.length || 4
        }
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
    selectCoin(coin) {
      this.config.coin = coin.ticker
      this.config.poolUrl = coin.poolUrl
      this.config.explorerUrl = coin.explorerUrl
    },

    changeMinerCount(delta) {
      const next = Math.max(1, Math.min(50, this.config.minerCount + delta))
      if (next === this.config.minerCount) return
      this.config.minerCount = next
      const miners = this.config.miners.slice(0, next)
      while (miners.length < next) {
        miners.push({ name: `Miner ${miners.length + 1}`, ip: '' })
      }
      this.config.miners = miners
    },

    nextStep() {
      if (this.step === 1) {
        if (!this.config.poolUrl) {
          alert('Please enter a pool URL')
          return
        }
        if (!this.config.wallet) {
          alert('Please enter your wallet address')
          return
        }
      }
      this.step++
    },

    async saveConfig() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.config))
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
      this.config = defaultConfig()
    },

    startPolling() {
      if (this.pollInterval) clearInterval(this.pollInterval)
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

    formatReward(val) {
      if (!val) return '0'
      if (val >= 1e6) return (val / 1e6).toFixed(2) + 'M'
      if (val >= 1e3) return val.toFixed(2)
      return val.toFixed(4)
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