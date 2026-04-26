"""
EconSim - Economy Simulator
A local web-based economic simulation dashboard.
"""

from flask import Flask, render_template, jsonify, request, send_file
import sqlite3
import os
import random
import threading
import time
import json

app = Flask(__name__)
app.config['DATABASE'] = 'ecsim.db'

# Simulation state
simulation = {
    'running': False,
    'tick_interval': 1.0,
    'tick_count': 0,
    'thread': None
}

# Agent behavior config
AGENT_PRODUCE_CHANCE = 0.1
AGENT_PROCESS_CHANCE = 0.2
AGENT_FACTORY_CHANCE = 0.35
AGENT_CONSUME_CHANCE = 0.4
AGENT_TRADE_CHANCE = 0.5
MIN_BALANCE = 10.0
EVENT_CHANCE = 0.05

# Wealth redistribution config
WEALTH_TAX_RATE = 0.03        # 3% tax on balances above threshold
WEALTH_TAX_THRESHOLD = 5000.0  # agents below this keep all their money
WEALTH_MINIMUM = 50.0         # agents guaranteed this minimum balance
WEALTH_REDIST_INTERVAL = 10    # fire redistribution every N ticks (smooths economy)

# Production chains
# Production chains — factories (agent-owned mills)
# Stage 1: Raw goods processed into refined goods
PRODUCTION_CHAINS = {
    'Flour':     {'inputs': {'Wheat': 2},          'output': 'Flour',     'output_qty': 1, 'base_price': 45.00},
    'Iron Bars': {'inputs': {'Iron': 2},            'output': 'Iron Bars', 'output_qty': 1, 'base_price': 120.00},
    'Gold Bars': {'inputs': {'Gold': 2},            'output': 'Gold Bars', 'output_qty': 1, 'base_price': 1200.00},
    'Lumber':    {'inputs': {'Wood': 2},            'output': 'Lumber',    'output_qty': 1, 'base_price': 65.00},
    'Steel':     {'inputs': {'Iron Bars': 1, 'Coal': 1}, 'output': 'Steel', 'output_qty': 1, 'base_price': 280.00},
    'Fuel':      {'inputs': {'Oil': 2},             'output': 'Fuel',      'output_qty': 1, 'base_price': 40.00},
}

# Mines — extract raw materials from the ground
# Each mine produces its raw good directly (no intermediate ore step)
MINES = {
    'Iron Mine':    {'output': 'Iron',   'fee_per_unit': 5.0,  'base_price': 50.00},
    'Coal Mine':    {'output': 'Coal',   'fee_per_unit': 3.0,  'base_price': 35.00},
    'Gold Mine':    {'output': 'Gold',   'fee_per_unit': 10.0, 'base_price': 200.00},
    'Oil Mine':     {'output': 'Oil',    'fee_per_unit': 4.0,  'base_price': 45.00},
    'Wheat Farm':   {'output': 'Wheat',  'fee_per_unit': 2.0,  'base_price': 25.00},
    'Wood Mine':    {'output': 'Wood',   'fee_per_unit': 3.0,  'base_price': 30.00},
}

# Initial agent seed data — used for both first-run and reset
INITIAL_AGENTS = [
    ('Alice',   'producer',  6000.0, {'Wheat': 6, 'Wood': 4}),
    ('Bob',     'producer',  7000.0, {'Iron': 5, 'Coal': 4}),
    ('Henry',   'producer',  8500.0, {'Gold': 3, 'Iron': 4, 'Coal': 3}),
    ('Carol',   'processor', 10000.0, {'Wheat': 4, 'Iron': 3, 'Coal': 2}),
    ('Dave',    'processor', 12000.0, {'Iron': 4, 'Coal': 4}),
    ('Diana',   'consumer',  5000.0, {'Bread': 2, 'Furniture': 1}),
    ('Grace',   'consumer',  4500.0, {'Flour': 2, 'Lumber': 2}),
    ('Frank',   'trader',   18000.0, {'Gold Bars': 1, 'Steel': 1, 'Tools': 1}),
]

# Shops — buy refined goods, produce finished goods, inject money into economy
# Stage 2: Refined goods processed into finished goods
SHOP_RECIPES = {
    'Bakery':      {'inputs': {'Flour': 3},         'output': 'Bread',     'buy_price_mult': 0.90, 'initial_cash': 5000,   'mill': 'Flour Mill'},
    'Jeweler':     {'inputs': {'Gold Bars': 2},      'output': 'Jewelry',   'buy_price_mult': 0.90, 'initial_cash': 10000,  'mill': 'Gold Bars Mill'},
    'Carpenter':   {'inputs': {'Lumber': 3},         'output': 'Furniture', 'buy_price_mult': 0.90, 'initial_cash': 5000,   'mill': 'Lumber Mill'},
    'Blacksmith':  {'inputs': {'Steel': 2},          'output': 'Tools',     'buy_price_mult': 0.90, 'initial_cash': 5000,   'mill': 'Steel Mill'},
}

# Finished goods prices (what shops output — used by market and agents)
FINISHED_GOODS = {
    'Bread':     {'base_price': 80.00,  'happiness': 0.10},
    'Jewelry':   {'base_price': 2500.00,'happiness': 0.20},
    'Furniture': {'base_price': 150.00, 'happiness': 0.12},
    'Tools':     {'base_price': 400.00, 'happiness': 0.08},
    'Steel':     {'base_price': 280.00, 'happiness': 0.06},
    'Fuel':      {'base_price': 25.00,  'happiness': 0.04},
}

RAW_GOODS = ['Wheat', 'Iron', 'Gold', 'Oil', 'Wood', 'Coal']
REFINED_GOODS = list(PRODUCTION_CHAINS.keys())  # Flour, Iron Bars, Gold Bars, Lumber, Steel, Fuel
FINISHED_LIST = list(FINISHED_GOODS.keys())       # Bread, Jewelry, Furniture, Tools, Steel, Fuel
ALL_GOODS = RAW_GOODS + REFINED_GOODS + FINISHED_LIST


def get_db():
    conn = sqlite3.connect(app.config['DATABASE'], timeout=10.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            agent_type TEXT NOT NULL,
            balance REAL DEFAULT 1000.0,
            inventory TEXT DEFAULT '{}',
            happiness REAL DEFAULT 0.5,
            reputation REAL DEFAULT 0.5,
            total_contracts INTEGER DEFAULT 0,
            fulfilled_contracts INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_agent INTEGER,
            to_agent INTEGER NOT NULL,
            amount REAL NOT NULL,
            good_name TEXT,
            quantity INTEGER,
            transaction_type TEXT DEFAULT 'transfer',
            description TEXT,
            tick INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (from_agent) REFERENCES agents(id),
            FOREIGN KEY (to_agent) REFERENCES agents(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            good_name TEXT UNIQUE NOT NULL,
            current_price REAL DEFAULT 10.0,
            base_price REAL DEFAULT 10.0,
            supply INTEGER DEFAULT 100,
            demand INTEGER DEFAULT 100,
            volatility REAL DEFAULT 0.1,
            elasticity REAL DEFAULT 0.5,
            is_refined INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT,
            tick INTEGER,
            data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tick INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_money REAL,
            gini_coefficient REAL,
            num_transactions INTEGER,
            avg_price REAL,
            inflation_rate REAL,
            total_refined INTEGER DEFAULT 0,
            factories_active INTEGER DEFAULT 0,
            shops_count INTEGER DEFAULT 0,
            money_injected REAL DEFAULT 0,
            money_sunk REAL DEFAULT 0,
            processing_count INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sim_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # ---- CONTRACTS ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            seller_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            good_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price_per_unit REAL NOT NULL,
            delivery_tick INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            reputation_impact REAL DEFAULT 0.05,
            created_tick INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES agents(id),
            FOREIGN KEY (seller_id) REFERENCES agents(id),
            FOREIGN KEY (buyer_id) REFERENCES agents(id)
        )
    ''')

    # ---- CONTRACT LOG ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contract_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER,
            seller_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            good_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            total_price REAL NOT NULL,
            status TEXT NOT NULL,
            tick INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contract_id) REFERENCES contracts(id),
            FOREIGN KEY (seller_id) REFERENCES agents(id),
            FOREIGN KEY (buyer_id) REFERENCES agents(id)
        )
    ''')
    # ---- FACTORIES ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS factories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            produces TEXT NOT NULL,
            owner_id INTEGER,
            shop_id INTEGER,
            fee_per_unit REAL DEFAULT 10.0,
            level INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES agents(id),
            FOREIGN KEY (shop_id) REFERENCES shops(id),
            UNIQUE(produces, owner_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factory_id INTEGER,
            customer_id INTEGER NOT NULL,
            input_goods TEXT NOT NULL,
            output_good TEXT NOT NULL,
            output_qty INTEGER NOT NULL,
            fee_paid REAL NOT NULL,
            tick INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (factory_id) REFERENCES factories(id),
            FOREIGN KEY (customer_id) REFERENCES agents(id)
        )
    ''')

    # ---- MINES ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            produces TEXT NOT NULL UNIQUE,
            owner_id INTEGER,
            fee_per_unit REAL DEFAULT 5.0,
            level INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES agents(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mine_id INTEGER,
            customer_id INTEGER NOT NULL,
            output_good TEXT NOT NULL,
            output_qty INTEGER NOT NULL,
            fee_paid REAL NOT NULL,
            tick INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (mine_id) REFERENCES mines(id),
            FOREIGN KEY (customer_id) REFERENCES agents(id)
        )
    ''')

    # ---- SHOPS ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            input_good TEXT NOT NULL,
            output_good TEXT NOT NULL,
            buy_price_mult REAL DEFAULT 0.7,
            mill_id INTEGER,
            cash REAL DEFAULT 0.0,
            inventory TEXT DEFAULT '{}',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (mill_id) REFERENCES factories(id)
        )
    ''')

    # Auto-seed on first run if no agents exist
    cursor.execute('SELECT COUNT(*) FROM agents')
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            'INSERT INTO agents (name, agent_type, balance, inventory, happiness) VALUES (?,?,?,?,?)',
            [(n, t, b, json.dumps(i), 0.6) for n, t, b, i in INITIAL_AGENTS]
        )

    # Seed market if empty
    cursor.execute('SELECT COUNT(*) FROM market')
    if cursor.fetchone()[0] == 0:
        all_goods = RAW_GOODS + list(PRODUCTION_CHAINS.keys()) + list(FINISHED_GOODS.keys())
        for g in all_goods:
            if g in FINISHED_GOODS:
                base_price = FINISHED_GOODS[g]['base_price']
                is_refined = 1
            elif g in PRODUCTION_CHAINS:
                base_price = PRODUCTION_CHAINS[g]['base_price']
                is_refined = 1
            else:
                base_price = 25.0
                is_refined = 0
            cursor.execute(
                'INSERT OR IGNORE INTO market (good_name, base_price, current_price, supply, demand, volatility, elasticity, is_refined) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (g, base_price, base_price, 70, 70, 0.15, 0.5, is_refined))

    conn.commit()
    conn.close()


def get_state(key, default=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM sim_state WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default


def set_state(key, value):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO sim_state (key, value) VALUES (?, ?)',
                   (key, str(value)))
    conn.commit()
    conn.close()


def parse_inventory(inv_str):
    if not inv_str:
        return {}
    if isinstance(inv_str, dict):
        return inv_str
    try:
        return json.loads(inv_str)
    except:
        return {}


def inventory_to_json(inv):
    return json.dumps(inv)


def calculate_gini(agents):
    if len(agents) < 2:
        return 0.0
    balances = sorted([a['balance'] for a in agents])
    n = len(balances)
    cumsum = sum(balances)
    if cumsum == 0:
        return 0.0
    weighted_sum = sum((i + 1) * b for i, b in enumerate(balances))
    gini = (2 * weighted_sum) / (n * cumsum) - (n + 1) / n
    return max(0.0, min(1.0, gini))


def price_from_supply_demand(supply, demand, base_price, volatility, elasticity=0.5):
    if supply == 0:
        ratio = 3.0
    else:
        ratio = demand / supply
    price_multiplier = 1 + (ratio - 1) * elasticity
    price_multiplier *= (1 + random.uniform(-volatility, volatility))
    price = base_price * price_multiplier
    price = max(base_price * 0.1, min(base_price * 10.0, price))
    return round(price, 2)


# ============ ECONOMIC EVENTS ============

def record_event(conn, name, event_type, description, data=None):
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO events (event_name, event_type, description, tick, data)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, event_type, description, simulation['tick_count'], json.dumps(data) if data else None))
    conn.commit()
    return cursor.lastrowid


def apply_gold_rush(conn):
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents ORDER BY RANDOM() LIMIT 1')
    lucky = cursor.fetchone()
    if lucky:
        bonus = random.uniform(2000, 5000)
        cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (bonus, lucky['id']))
        conn.commit()
        record_event(conn, 'Gold Rush', 'positive',
                     '\U0001f4b0 %s struck gold! +$%.0f' % (lucky['name'], bonus),
                     {'agent_id': lucky['id'], 'bonus': bonus})
    return True


def apply_recession(conn):
    cursor = conn.cursor()
    cursor.execute('UPDATE agents SET happiness = MAX(0, happiness - 0.2)')
    cursor.execute('SELECT COUNT(*) as count FROM agents')
    count = cursor.fetchone()['count']
    conn.commit()
    record_event(conn, 'Recession', 'negative',
                 '\U0001f4c9 Recession! Happiness dropped', {})
    return True


def apply_prosperity(conn):
    cursor = conn.cursor()
    cursor.execute('UPDATE agents SET happiness = MIN(1.0, happiness + 0.3)')
    cursor.execute('SELECT COUNT(*) as count FROM agents')
    count = cursor.fetchone()['count']
    conn.commit()
    record_event(conn, 'Prosperity', 'positive',
                 '\U0001f31f Prosperity! Happiness +30%%', {'count': count})
    return True


def apply_tech_boom(conn):
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM factories WHERE level < 5 AND active = 1 ORDER BY RANDOM() LIMIT 2')
    upgraded = cursor.fetchall()
    for f in upgraded:
        cursor.execute('UPDATE factories SET level = level + 1, fee_per_unit = fee_per_unit * 0.9 WHERE id = ?', (f['id'],))
    conn.commit()
    record_event(conn, 'Tech Boom', 'positive',
                 '\U0001f680 Tech boom! %d factories upgraded' % len(upgraded),
                 {'count': len(upgraded)})
    return True


def apply_supply_shock(conn):
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM market ORDER BY RANDOM() LIMIT 1')
    good = cursor.fetchone()
    if good:
        change = random.randint(-70, -15)
        cursor.execute('UPDATE market SET supply = MAX(1, supply + ?) WHERE good_name = ?',
                       (change, good['good_name']))
        conn.commit()
        record_event(conn, 'Supply Shock', 'negative',
                     '\u26a1 Supply shock! %s %+d' % (good['good_name'], change),
                     {'good': good['good_name'], 'change': change})
    return True


def apply_inflation(conn):
    cursor = conn.cursor()
    money_injection = random.uniform(1000, 3000)
    cursor.execute('SELECT * FROM agents ORDER BY RANDOM() LIMIT 3')
    for t in cursor.fetchall():
        share = money_injection / 3
        cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (share, t['id']))
    cursor.execute('SELECT * FROM market')
    for g in cursor.fetchall():
        cursor.execute('UPDATE market SET current_price = current_price * ? WHERE good_name = ?',
                       (random.uniform(1.1, 1.3), g['good_name']))
    conn.commit()
    record_event(conn, 'Inflation Event', 'negative',
                 '\U0001f4b5 Money printed! Prices surge 10-30%%', {})
    return True


def apply_refined_demand(conn):
    refined = list(PRODUCTION_CHAINS.keys())
    cursor = conn.cursor()
    good_name = random.choice(refined)
    cursor.execute('SELECT * FROM market WHERE good_name = ?', (good_name,))
    good = cursor.fetchone()
    if good:
        boost = random.randint(80, 200)
        cursor.execute('UPDATE market SET demand = demand + ? WHERE good_name = ?',
                       (boost, good_name))
        conn.commit()
        record_event(conn, 'Refined Demand', 'positive',
                     '\U0001f4c8 Demand surge! %s demand +%d' % (good_name, boost),
                     {'good': good_name, 'boost': boost})
    return True


def apply_export_boom(conn):
    cursor = conn.cursor()
    good_name = random.choice(RAW_GOODS)
    cursor.execute('SELECT * FROM market WHERE good_name = ?', (good_name,))
    good = cursor.fetchone()
    if good:
        boost = random.randint(100, 250)
        cursor.execute('UPDATE market SET demand = demand + ? WHERE good_name = ?',
                       (boost, good_name))
        conn.commit()
        record_event(conn, 'Export Boom', 'positive',
                     '\U0001f30d Export boom! %s demand +%d' % (good_name, boost),
                     {'good': good_name, 'boost': boost})
    return True


def apply_factory_fire(conn):
    cursor = conn.cursor()
    cursor.execute('SELECT f.*, a.name as owner_name FROM factories f LEFT JOIN agents a ON f.owner_id = a.id WHERE f.active = 1 ORDER BY RANDOM() LIMIT 1')
    factory = cursor.fetchone()
    if factory:
        cursor.execute('UPDATE factories SET active = 0 WHERE id = ?', (factory['id'],))
        conn.commit()
        owner_info = (' (owned by %s)' % factory['owner_name']) if factory['owner_id'] else ''
        record_event(conn, 'Factory Fire', 'negative',
                     '\U0001f525 %s burned down!%s' % (factory['name'], owner_info),
                     {'factory_id': factory['id']})
    return True


def apply_new_competitor(conn):
    cursor = conn.cursor()
    cursor.execute('SELECT produces, COUNT(*) as cnt FROM factories WHERE active = 1 GROUP BY produces')
    counts = {row['produces']: row['cnt'] for row in cursor.fetchall()}
    candidates = [g for g in PRODUCTION_CHAINS if counts.get(g, 0) < 1]
    if not candidates:
        return True
    good = random.choice(candidates)
    cursor.execute('SELECT MIN(balance) as min_bal FROM agents')
    min_bal = cursor.fetchone()['min_bal'] or 1000
    cursor.execute('SELECT * FROM agents WHERE balance > ? ORDER BY RANDOM() LIMIT 1', (min_bal,))
    owner = cursor.fetchone()
    if not owner:
        conn.commit()
        return True
    base = PRODUCTION_CHAINS[good]['base_price']
    fee = base * random.uniform(0.03, 0.08)
    factory_name = good + ' Mill'
    cursor.execute('''
        INSERT INTO factories (name, produces, owner_id, fee_per_unit, level, active)
        VALUES (?, ?, ?, ?, 1, 1)
    ''', (factory_name, good, owner['id'], round(fee, 2)))
    fid = cursor.lastrowid
    conn.commit()
    record_event(conn, 'New Competitor', 'positive',
                 '\U0001f3d7 %s opened (%s enters market)' % (factory_name, owner['name']),
                 {'factory_id': fid, 'good': good, 'owner': owner['name']})
    return True


def apply_shop_opens(conn):
    """A new shop opens and stocks up."""
    cursor = conn.cursor()
    # See which shops already exist (by shop name)
    cursor.execute('SELECT name FROM shops WHERE active = 1')
    existing = {row['name'] for row in cursor.fetchall()}
    # Find a shop recipe not yet in use
    available = [s for s in SHOP_RECIPES if s not in existing]
    if not available:
        return True
    shop_name = random.choice(available)
    recipe = SHOP_RECIPES[shop_name]
    # Shops are publicly owned — no agent balance is deducted
    owner_id = None  # public investor (no single owner)
    cash = recipe['initial_cash']
    cursor.execute('''
        INSERT INTO shops (name, input_good, output_good, buy_price_mult, cash, inventory, active)
        VALUES (?, ?, ?, ?, ?, '{}', 1)
    ''', (shop_name, list(recipe['inputs'].keys())[0], recipe['output'], recipe['buy_price_mult'], cash))
    sid = cursor.lastrowid

    # Create a dedicated mill for this shop
    mill_name = recipe.get('mill')
    if mill_name:
        mill_produces = None
        for refined_good, chain in PRODUCTION_CHAINS.items():
            if chain['output'] == list(recipe['inputs'].keys())[0]:
                mill_produces = refined_good
                break
        if mill_produces:
            # Remove any existing mill with this name (UNIQUE constraint on produces blocks INSERT OR IGNORE)
            cursor.execute('DELETE FROM factories WHERE name = ?', (mill_name,))
            cursor.execute('''
                INSERT INTO factories (name, produces, owner_id, shop_id, fee_per_unit, level, active)
                VALUES (?, ?, ?, ?, ?, 1, 1)
            ''', (mill_name, mill_produces, owner_id, sid, 0.0))
            # Set shop's mill_id
            cursor.execute('UPDATE shops SET mill_id = (SELECT id FROM factories WHERE name = ? AND shop_id = ?) WHERE id = ?',
                           (mill_name, sid, sid))


    owner_name = 'public investor'
    conn.commit()
    record_event(conn, 'Shop Opens', 'positive',
                 '\U0001f3ea %s opens! (public investor)' % shop_name,
                 {'shop_id': sid, 'shop': shop_name})
    return True


ECONOMIC_EVENTS = [
    ('gold_rush', apply_gold_rush),
    ('recession', apply_recession),
    ('prosperity', apply_prosperity),
    ('tech_boom', apply_tech_boom),
    ('supply_shock', apply_supply_shock),
    ('inflation', apply_inflation),
    ('refined_demand', apply_refined_demand),
    ('export_boom', apply_export_boom),
    ('new_competitor', apply_new_competitor),
    # NOTE: shop_opens removed — shops only open via dedicated 5% mechanic below
]


def trigger_random_event(conn):
    if random.random() > EVENT_CHANCE:
        return None
    event_func = random.choice(ECONOMIC_EVENTS)
    try:
        result = event_func[1](conn)
        return event_func[0]
    except Exception as e:
        print('Event error: %s' % e)
        return None


# ============ AGENT ACTIONS ============


# ============ UTILITY ============

def market_price(market_goods, good_name):
    for g in market_goods:
        if g['good_name'] == good_name:
            return g['current_price']
    return None

def get_market_dict(market_goods):
    return {g['good_name']: g['current_price'] for g in market_goods}

def profitable_factory_targets(inv, market_goods, conn):
    cursor = conn.cursor()
    prices = get_market_dict(market_goods)
    results = []
    for good_name, chain in PRODUCTION_CHAINS.items():
        has_all = True
        for input_good, needed in chain['inputs'].items():
            if inv.get(input_good, 0) < needed:
                has_all = False
                break
        if not has_all:
            continue
        cursor.execute('SELECT fee_per_unit FROM factories WHERE produces = ? AND active = 1 LIMIT 1', (good_name,))
        row = cursor.fetchone()
        if not row:
            continue
        fee_per_unit = row['fee_per_unit']
        output_qty = chain['output_qty']
        output_price = prices.get(good_name, chain['base_price'])
        revenue = output_price * output_qty
        profit = revenue - (fee_per_unit * output_qty)
        if profit > 0:
            results.append((good_name, profit))
    return results

def best_shop_for(conn, good_name, market_goods):
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM shops WHERE input_good = ? AND active = 1 AND cash >= 1 ORDER BY buy_price_mult DESC',
        (good_name,))
    shops = cursor.fetchall()
    if not shops:
        return None
    prices = get_market_dict(market_goods)
    market_p = prices.get(good_name, 0)
    best, best_unit = None, 0
    for s in shops:
        unit = market_p * s['buy_price_mult']
        if unit > best_unit:
            best_unit = unit
            best = s
    return (best, best_unit) if best else None

def find_fair_trade(conn, agent, market_goods):
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents WHERE id != ? ORDER BY RANDOM() LIMIT 5', (agent['id'],))
    partners = cursor.fetchall()
    if not partners:
        return None
    prices = get_market_dict(market_goods)
    agent_inv = parse_inventory(agent['inventory'])
    for partner in partners:
        partner_inv = parse_inventory(partner['inventory'])
        for g in market_goods:
            gname = g['good_name']
            if partner_inv.get(gname, 0) == 0:
                continue
            price = prices.get(gname, g['current_price'])
            for q in range(1, min(partner_inv.get(gname, 0), 3) + 1):
                cost = price * q
                if agent['balance'] >= cost and cost <= agent['balance'] * 0.25:
                    return (partner, gname, q, cost)
        for gname, aqty in list(agent_inv.items()):
            if gname not in prices:
                continue
            price = prices[gname]
            for q in range(1, min(aqty, 3) + 1):
                earnings = price * q
                if partner['balance'] >= earnings and earnings <= partner['balance'] * 0.25:
                    return (partner, gname, -q, earnings)
    return None

# ============ AGENT ACTIONS ============

def agent_produce(conn, agent, market_goods):
    if random.random() > AGENT_PRODUCE_CHANCE:
        return None
    prices = get_market_dict(market_goods)
    candidates = []
    for raw in RAW_GOODS:
        base = next((g['base_price'] for g in market_goods if g['good_name'] == raw), None)
        if not base:
            continue
        cur = prices.get(raw, base)
        candidates.append((raw, cur / base if base > 0 else 0.5, base))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[1])
    top = candidates[:max(1, len(candidates) // 2)]
    raw, ratio, base = random.choice(top)
    # Produce more when price is high
    quantity = random.randint(2, 4) if ratio > 0.85 else random.randint(1, 3)
    production_cost = prices.get(raw, base) * random.uniform(0.03, 0.08) * quantity
    if agent['balance'] < production_cost:
        return None
    cursor = conn.cursor()
    cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (production_cost, agent['id']))
    inv = parse_inventory(agent['inventory'])
    inv[raw] = inv.get(raw, 0) + quantity
    cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?',
                   (inventory_to_json(inv), agent['id']))
    tx_desc = 'Produced %d %s' % (quantity, raw)
    cursor.execute(
        'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (None, agent['id'], production_cost, raw, quantity, 'production', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'produce:%s' % raw

def agent_use_factory(conn, agent, market_goods):
    if random.random() > AGENT_FACTORY_CHANCE:
        return None
    cursor = conn.cursor()
    inv = parse_inventory(agent['inventory'])
    profitable = profitable_factory_targets(inv, market_goods, conn)
    if not profitable:
        return None
    profitable.sort(key=lambda x: -x[1])
    top = profitable[:min(3, len(profitable))]
    target_good, expected_profit = random.choice(top)
    chain = PRODUCTION_CHAINS[target_good]
    cursor.execute(
        'SELECT f.*, a.name as owner_name FROM factories f '
        'LEFT JOIN agents a ON f.owner_id = a.id '
        'WHERE f.produces = ? AND f.active = 1 ORDER BY f.fee_per_unit ASC LIMIT 1',
        (target_good,))
    factory = cursor.fetchone()
    if not factory:
        return None
    output_qty = chain['output_qty']
    efficiency = 0.85 + (factory['level'] * 0.12)
    if agent['agent_type'] == 'processor':
        efficiency *= 1.15
    output_qty = max(1, int(output_qty * efficiency))
    total_fee = factory['fee_per_unit'] * output_qty
    if agent['balance'] < total_fee:
        return None
    for input_good, needed in chain['inputs'].items():
        inv[input_good] -= needed
        if inv[input_good] <= 0:
            del inv[input_good]
    owner_id = factory['owner_id'] if factory['owner_id'] else None
    cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (total_fee, agent['id']))
    if owner_id:
        cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (total_fee, owner_id))
    inv[target_good] = inv.get(target_good, 0) + output_qty
    cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?',
                   (inventory_to_json(inv), agent['id']))
    cursor.execute('UPDATE market SET supply = supply + ? WHERE good_name = ?',
                   (output_qty, target_good))
    cursor.execute(
        'INSERT INTO processing_log (factory_id, customer_id, input_goods, output_good, output_qty, fee_paid, tick) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (factory['id'], agent['id'], json.dumps(chain['inputs']), target_good, output_qty, total_fee, simulation['tick_count']))
    # Record transaction ONLY when using someone else's factory (net balance change is non-zero)
    if owner_id and owner_id != agent['id']:
        tx_desc = 'Used %s > %dx %s' % (factory['name'], output_qty, target_good)
        cursor.execute(
            'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (agent['id'], owner_id, -abs(total_fee), target_good, output_qty, 'factory_use', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'factory:%s' % target_good

def agent_build_factory(conn, agent):
    cursor = conn.cursor()
    cursor.execute('SELECT produces, COUNT(*) as cnt FROM factories WHERE active = 1 GROUP BY produces')
    counts = {row['produces']: row['cnt'] for row in cursor.fetchall()}
    missing = [g for g in PRODUCTION_CHAINS if counts.get(g, 0) == 0]
    if not missing:
        return None
    candidates = []
    for target_good in missing:
        chain = PRODUCTION_CHAINS[target_good]
        base_price = chain['base_price']
        cost = base_price * random.uniform(0.8, 1.5)
        fee = base_price * random.uniform(0.03, 0.08)
        # Estimated 0.2 uses/tick * 100 ticks per cycle
        daily_revenue = fee * 40
        roi_ticks = cost / daily_revenue if daily_revenue > 0 else 9999
        candidates.append((target_good, cost, fee, roi_ticks))
    affordable = [(g, c, f, r) for g, c, f, r in candidates
                  if c <= agent['balance'] * 0.5 and r < 80]
    if not affordable:
        affordable = [(g, c, f, r) for g, c, f, r in candidates if c <= agent['balance'] * 0.8]
        if not affordable:
            return None
    affordable.sort(key=lambda x: x[3])
    target_good, cost, fee, roi_ticks = affordable[0]
    # Build cost is real — agents pay to construct infrastructure
    if cost > 0 and agent['balance'] < cost:
        return None
    factory_name = target_good + ' Mill'
    cursor.execute('INSERT OR IGNORE INTO factories (name, produces, owner_id, fee_per_unit, level, active) VALUES (?, ?, ?, ?, 1, 1)',
                  (factory_name, target_good, agent['id'], round(fee, 2)))
    if cursor.rowcount == 0:
        return None  # another agent beat us to it
    if cost > 0:
        cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (cost, agent['id']))
    tx_desc = 'Built %s (ROI: ~%d ticks)' % (factory_name, int(roi_ticks))
    cursor.execute(
        'INSERT INTO transactions (from_agent, to_agent, amount, transaction_type, description, tick) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (agent['id'], agent['id'], cost, 'factory_build', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'built:%s' % target_good

def agent_build_mine(conn, agent, market_goods):
    """Build a mine to extract ore."""
    if random.random() > 0.25:  # mines are less rare now with more raw material demand
        return None
    cursor = conn.cursor()
    candidates = []
    for mine_name, mine in MINES.items():
        cursor.execute('SELECT COUNT(*) FROM mines WHERE name = ? AND active = 1', (mine_name,))
        if cursor.fetchone()[0] > 0:
            continue
        base_price = mine['base_price']
        fee = base_price * random.uniform(0.03, 0.08)
        roi_ticks = 50  # estimate
        candidates.append((mine_name, 0, fee, roi_ticks))
    if not candidates:
        return None
    target_mine, cost, fee, roi_ticks = random.choice(candidates)
    mine = MINES[target_mine]
    cursor.execute(
        'INSERT OR IGNORE INTO mines (name, produces, owner_id, fee_per_unit, level, active) VALUES (?, ?, ?, ?, 1, 1)',
        (target_mine, mine['output'], agent['id'], round(fee, 2)))
    if cursor.rowcount == 0:
        return None
    tx_desc = 'Built %s' % target_mine
    cursor.execute(
        'INSERT INTO transactions (from_agent, to_agent, amount, transaction_type, description, tick) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (agent['id'], agent['id'], 0, 'mine_build', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'built:%s' % target_mine

def agent_process(conn, agent, market_goods):
    if random.random() > AGENT_PROCESS_CHANCE:
        return None
    cursor = conn.cursor()
    inv = parse_inventory(agent['inventory'])
    prices = get_market_dict(market_goods)
    for good_name, chain in PRODUCTION_CHAINS.items():
        cursor.execute('SELECT COUNT(*) FROM factories WHERE produces = ? AND active = 1', (good_name,))
        if cursor.fetchone()[0] > 0:
            continue
        has_all = True
        for input_good, needed in chain['inputs'].items():
            if inv.get(input_good, 0) < needed:
                has_all = False
                break
        if not has_all:
            continue
        output_price = prices.get(good_name, chain['base_price'])
        revenue = output_price * chain['output_qty']
        input_cost = sum(prices.get(ing, 0) * chain['inputs'][ing] for ing in chain['inputs'])
        if revenue <= input_cost * 1.1:
            continue
        for input_good, needed in chain['inputs'].items():
            inv[input_good] -= needed
            if inv[input_good] <= 0:
                del inv[input_good]
        output_qty = chain['output_qty']
        inv[chain['output']] = inv.get(chain['output'], 0) + output_qty
        cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?',
                       (inventory_to_json(inv), agent['id']))
        cursor.execute('UPDATE market SET supply = supply + ? WHERE good_name = ?',
                       (output_qty, chain['output']))
        tx_desc = 'Hand-processed %dx %s' % (output_qty, chain['output'])
        cursor.execute(
            'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (agent['id'], agent['id'], 0, chain['output'], output_qty, 'processing', tx_desc, simulation['tick_count']))
        conn.commit()
        return 'process:%s' % chain['output']
    return None

def agent_sell_to_shop(conn, agent, market_goods):
    """Agents sell goods (raw or refined) to shops. Shops use mills to refine raw materials."""
    if random.random() > 0.25:
        return None
    cursor = conn.cursor()
    inv = parse_inventory(agent['inventory'])
    prices = get_market_dict(market_goods)
    # Collect goods the agent has (raw or refined)
    has_goods = [g for g, qty in inv.items() if qty > 0]
    if not has_goods:
        return None
    random.shuffle(has_goods)
    target_good = None
    for good in has_goods:
        if good in RAW_GOODS or good in REFINED_GOODS:
            target_good = good
            break
    if not target_good:
        return None
    qty = min(random.randint(1, 3), inv.get(target_good, 0))
    if qty == 0:
        return None
    # Find shops that want this good (shops whose mill consumes it as raw input)
    cursor.execute('SELECT * FROM shops WHERE active = 1 AND mill_id IS NOT NULL AND cash > 0')
    shops = [dict(row) for row in cursor.fetchall()]
    if not shops:
        return None
    candidates = []
    for shop in shops:
        cursor.execute('SELECT * FROM factories WHERE id = ? AND active = 1', (shop['mill_id'],))
        mill = cursor.fetchone()
        if not mill:
            continue
        mill_output = mill['produces']  # e.g. 'Gold Bars'
        chain = PRODUCTION_CHAINS.get(mill_output)
        if not chain:
            continue
        raw_inputs = list(chain['inputs'].keys())  # e.g. ['Gold']
        if target_good not in raw_inputs:
            continue
        market_p = prices.get(target_good, 0)
        unit_price = market_p * shop['buy_price_mult']  # 90% of market
        if unit_price > 0:
            candidates.append((shop, target_good, unit_price))
    if not candidates:
        return None
    shop, target_good, unit_price = random.choice(candidates)
    total = unit_price * qty
    if shop['cash'] < total:
        qty = max(1, int(shop['cash'] / unit_price))
        total = unit_price * qty
    if qty == 0 or total <= 0:
        return None
    inv[target_good] -= qty
    if inv[target_good] <= 0:
        del inv[target_good]
    cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?',
                   (inventory_to_json(inv), agent['id']))
    cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?',
                   (total, agent['id']))
    cursor.execute('SELECT inventory FROM shops WHERE id = ?', (shop['id'],))
    shop_inv_raw = cursor.fetchone()['inventory'] or '{}'
    try:
        shop_inv = json.loads(shop_inv_raw)
    except:
        shop_inv = {}
    shop_inv[target_good] = shop_inv.get(target_good, 0) + qty
    cursor.execute('UPDATE shops SET cash = cash - ?, inventory = ? WHERE id = ?',
                  (total, json.dumps(shop_inv), shop['id']))
    tx_desc = 'Sold %dx %s to %s' % (qty, target_good, shop['name'])
    cursor.execute(
        'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (agent['id'], -shop['id'], total, target_good, qty, 'shop_sell', tx_desc, simulation['tick_count']))
    conn.commit()
    return True


def agent_sell_to_market(conn, agent, market_goods):
    """Agent sells any good directly to the market at 85% of market price."""
    if random.random() > 0.20:
        return None
    cursor = conn.cursor()
    inv = parse_inventory(agent['inventory'])
    prices = get_market_dict(market_goods)
    has_goods = [g for g in inv if inv[g] > 0 and g in prices]
    if not has_goods:
        return None
    target_good = random.choice(has_goods)
    qty = min(random.randint(1, 3), inv.get(target_good, 0))
    if qty == 0:
        return None
    price = prices.get(target_good, 0)
    if price <= 0:
        return None
    unit_price = price * 0.85
    total = unit_price * qty
    inv[target_good] -= qty
    if inv[target_good] <= 0:
        del inv[target_good]
    cursor.execute('UPDATE agents SET inventory = ?, balance = balance + ? WHERE id = ?',
                   (inventory_to_json(inv), total, agent['id']))
    cursor.execute('UPDATE market SET demand = demand + ? WHERE good_name = ?', (qty, target_good))
    tx_desc = 'Sold %dx %s to market' % (qty, target_good)
    cursor.execute(
        'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (agent['id'], -1, total, target_good, qty, 'market_sell', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'market_sell:%s' % target_good


def agent_buy_from_shop(conn, agent, market_goods):
    """Shop sells finished goods to agent (shop turns refined inputs into finished outputs)."""
    if random.random() > 0.20:
        return None
    cursor = conn.cursor()
    inv = parse_inventory(agent['inventory'])
    prices = get_market_dict(market_goods)
    # Find shops that have inventory (finished goods ready to sell)
    cursor.execute('SELECT * FROM shops WHERE active = 1 AND cash > 0')
    shops = cursor.fetchall()
    if not shops:
        return None
    # Pick a shop that has output goods in inventory
    candidates = []
    for shop in shops:
        shop_inv_raw = shop['inventory'] or '{}'
        try:
            shop_inv = json.loads(shop_inv_raw)
        except:
            continue
        output_good = None
        for good_name, qty in shop_inv.items():
            if qty > 0 and good_name in FINISHED_GOODS:
                output_good = good_name
                candidates.append((shop, output_good, qty))
                break
    if not candidates:
        return None
    # Pick a random candidate
    shop, output_good, stock_qty = random.choice(candidates)
    shop_price = FINISHED_GOODS[output_good]['base_price'] * random.uniform(1.0, 1.15)
    qty = min(random.randint(1, 2), stock_qty)
    total = shop_price * qty
    if total <= 0:
        return None
    if agent['balance'] < total:
        return None
    # Transfer goods and money
    inv[output_good] = inv.get(output_good, 0) + qty
    cursor.execute('UPDATE agents SET inventory = ?, balance = balance - ? WHERE id = ?',
                   (inventory_to_json(inv), total, agent['id']))
    # Update shop inventory and cash
    shop_inv_raw = shop['inventory'] or '{}'
    try:
        shop_inv = json.loads(shop_inv_raw)
    except:
        shop_inv = {}
    shop_inv[output_good] = max(0, shop_inv.get(output_good, 0) - qty)
    cursor.execute('UPDATE shops SET cash = cash + ?, inventory = ? WHERE id = ?',
                  (total, json.dumps(shop_inv), shop['id']))
    tx_desc = 'Bought %dx %s from %s' % (qty, output_good, shop['name'])
    # Money flows from agent to shop, so amount is negative for from_agent
    cursor.execute(
        'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (agent['id'], -shop['id'], -total, output_good, qty, 'shop_sell', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'shop_buy:%s' % output_good

def agent_consume(conn, agent, market_goods):
    if random.random() > AGENT_CONSUME_CHANCE:
        return None
    cursor = conn.cursor()
    inv = parse_inventory(agent['inventory'])
    available = [g for g in market_goods if inv.get(g['good_name'], 0) > 0
                and g['good_name'] in FINISHED_GOODS]
    if available:
        good = random.choice(available)
        gname = good['good_name']
        qty = min(random.randint(1, 2), inv[gname])
        inv[gname] -= qty
        if inv[gname] <= 0:
            del inv[gname]
        happiness = FINISHED_GOODS[gname]['happiness']
        cursor.execute('UPDATE agents SET inventory = ?, happiness = MIN(1.0, happiness + ?) WHERE id = ?',
                       (inventory_to_json(inv), happiness * qty, agent['id']))
        tx_desc = 'Consumed %dx %s' % (qty, gname)
        cursor.execute(
            'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (agent['id'], agent['id'], 0, gname, qty, 'consumption', tx_desc, simulation['tick_count']))
        conn.commit()
        return 'consume:%s' % gname
    budget = agent['balance'] * 0.40
    if budget < 5:
        return None
    affordable = [g for g in market_goods if g['good_name'] in FINISHED_GOODS
                 and g['current_price'] <= budget]
    if not affordable:
        return None
    affordable.sort(key=lambda g: g['current_price'])
    good = affordable[0]
    gname = good['good_name']
    max_q = min(3, int(budget / good['current_price']))
    if max_q == 0:
        return None
    quantity = random.randint(1, max_q)
    total = good['current_price'] * quantity
    cursor.execute('SELECT id FROM agents WHERE id != ? LIMIT 1', (agent['id'],))
    row = cursor.fetchone()
    if not row:
        return None
    cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (total, agent['id']))
    cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (total, row['id']))
    cursor.execute('UPDATE market SET supply = MAX(0, supply - ?), demand = demand + ? WHERE good_name = ?',
                   (quantity, quantity, gname))
    inv[gname] = inv.get(gname, 0) + quantity
    cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?',
                   (inventory_to_json(inv), agent['id']))
    happiness = FINISHED_GOODS[gname]['happiness']
    cursor.execute('UPDATE agents SET happiness = MIN(1.0, happiness + ?) WHERE id = ?',
                   (happiness * quantity, agent['id']))
    tx_desc = 'Bought %dx %s' % (quantity, gname)
    cursor.execute(
        'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (agent['id'], row['id'], -total, gname, quantity, 'purchase', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'purchase:%s' % gname

def agent_trade(conn, agent, market_goods):
    if random.random() > AGENT_TRADE_CHANCE:
        return None
    deal = find_fair_trade(conn, agent, market_goods)
    if not deal:
        return None
    cursor = conn.cursor()
    partner, gname, qty, value = deal
    if qty > 0:
        if agent['balance'] < value:
            return None
        cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (value, agent['id']))
        cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (value, partner['id']))
        agent_inv = parse_inventory(agent['inventory'])
        partner_inv = parse_inventory(partner['inventory'])
        partner_inv[gname] -= qty
        if partner_inv[gname] <= 0:
            del partner_inv[gname]
        agent_inv[gname] = agent_inv.get(gname, 0) + qty
        cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?', (inventory_to_json(agent_inv), agent['id']))
        cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?', (inventory_to_json(partner_inv), partner['id']))
        tx_desc = 'Bought %dx %s' % (qty, gname)
        cursor.execute(
            'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (agent['id'], partner['id'], -value, gname, qty, 'trade', tx_desc, simulation['tick_count']))
    else:
        qty = abs(qty)
        if qty == 0:
            return None
        agent_inv = parse_inventory(agent['inventory'])
        partner_inv = parse_inventory(partner['inventory'])
        agent_inv[gname] -= qty
        if agent_inv[gname] <= 0:
            del agent_inv[gname]
        partner_inv[gname] = partner_inv.get(gname, 0) + qty
        cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?', (inventory_to_json(agent_inv), agent['id']))
        cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?', (inventory_to_json(partner_inv), partner['id']))
        cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (value, agent['id']))
        cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (value, partner['id']))
        tx_desc = 'Sold %dx %s' % (qty, gname)
        cursor.execute(
            'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (partner['id'], agent['id'], -value, gname, qty, 'trade', tx_desc, simulation['tick_count']))
    conn.commit()
    return 'trade:%s' % gname


# ============ CONTRACTS ============

def agent_propose_contract(conn, agent, market_goods):
    """Agent offers a forward contract: lock in price + quantity for future delivery.
    Sellers must have goods in inventory (or own the mill that produces them).
    Buyers must have enough balance to pay."""
    if random.random() > 0.08:
        return None

    cursor = conn.cursor()
    agent_inv = parse_inventory(agent['inventory'])
    tick = simulation['tick_count']

    # --- What goods can this agent realistically sell? ---
    # Check 1: goods already in inventory (strongest signal)
    sellable = []
    for good, price in [(g['good_name'], g['current_price']) for g in market_goods]:
        have = agent_inv.get(good, 0)
        if have >= 1:
            sellable.append((good, price, have))

    # Check 2: refined goods from mills the agent owns (can produce before delivery)
    cursor.execute('SELECT produces FROM factories WHERE owner_id = ? AND active = 1 AND shop_id IS NULL', (agent['id'],))
    for row in cursor.fetchall():
        refined = row['produces']  # e.g. 'Flour', 'Steel'
        if refined in REFINED_GOODS:
            chain = PRODUCTION_CHAINS.get(refined)
            if chain:
                can_make = True
                for raw, amt in chain['inputs'].items():
                    if agent_inv.get(raw, 0) < amt:
                        can_make = False
                        break
                if can_make:
                    price = next((g['current_price'] for g in market_goods if g['good_name'] == refined), 0)
                    if price > 0:
                        sellable.append((refined, price, agent_inv.get(refined, 0)))

    # --- Decide role ---
    max_buy_value = agent['balance'] * 0.85

    if sellable:
        role = 'seller'
        chosen_good, current_price, have = random.choice(sellable)
        # Never propose more than you have in stock (stock is the safe fallback)
        quantity = random.randint(1, max(1, have))
    elif max_buy_value >= 100:
        # No goods to sell — try buying something affordable
        affordable = [(g['good_name'], g['current_price'])
                     for g in market_goods if g['current_price'] * 3 <= max_buy_value]
        if not affordable:
            return None
        role = 'buyer'
        chosen_good, current_price = random.choice(affordable)
        quantity = random.randint(1, 3)
    else:
        return None

    # --- Pick counterparty (prefer high-rep) ---
    cursor.execute('SELECT * FROM agents WHERE id != ? ORDER BY RANDOM() LIMIT 5', (agent['id'],))
    candidates = sorted([dict(row) for row in cursor.fetchall()], key=lambda a: -a['reputation'])
    if not candidates:
        return None
    counterparty = candidates[0]

    seller = agent if role == 'seller' else counterparty
    buyer = counterparty if role == 'seller' else agent

    # Validate buyer can afford it
    locked_price = current_price * random.uniform(0.85, 1.15)
    total_value = locked_price * quantity
    if buyer['balance'] < total_value:
        return None

    # Delivery: 8-18 ticks (shorter = more likely to fulfill)
    delivery_tick = tick + random.randint(8, 18)
    rep_impact = round(min(0.15, total_value / 2000), 4)

    cursor.execute('''
        INSERT INTO contracts (creator_id, seller_id, buyer_id, good_name, quantity, price_per_unit, delivery_tick, status, reputation_impact, created_tick)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
    ''', (agent['id'], seller['id'], buyer['id'], chosen_good, quantity, round(locked_price, 2), delivery_tick, rep_impact, tick))
    conn.commit()
    return 'contract_proposed:%s' % chosen_good


def resolve_contracts(conn):
    """Check pending contracts for maturity; execute or breach them."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, sa.name as seller_name, ba.name as buyer_name
        FROM contracts c
        JOIN agents sa ON c.seller_id = sa.id
        JOIN agents ba ON c.buyer_id = ba.id
        WHERE c.status = 'pending' AND c.delivery_tick <= ?
    ''', (simulation['tick_count'],))
    due = [dict(row) for row in cursor.fetchall()]
    if not due:
        return

    for contract in due:
        cursor.execute('SELECT * FROM agents WHERE id = ?', (contract['seller_id'],))
        seller = dict(cursor.fetchone())
        cursor.execute('SELECT * FROM agents WHERE id = ?', (contract['buyer_id'],))
        buyer = dict(cursor.fetchone())

        seller_inv = parse_inventory(seller['inventory'])
        buyer_inv = parse_inventory(buyer['inventory'])
        total_price = contract['price_per_unit'] * contract['quantity']
        fulfilled = False
        status_reason = ''

        # Check: does seller have the goods?
        if seller_inv.get(contract['good_name'], 0) >= contract['quantity']:
            # Check: does buyer have enough balance?
            if buyer['balance'] >= total_price:
                # Execute the contract
                # Transfer goods: seller → buyer
                seller_inv[contract['good_name']] -= contract['quantity']
                if seller_inv[contract['good_name']] <= 0:
                    del seller_inv[contract['good_name']]
                buyer_inv[contract['good_name']] = buyer_inv.get(contract['good_name'], 0) + contract['quantity']
                # Transfer money: buyer → seller
                cursor.execute('UPDATE agents SET balance = balance - ?, inventory = ? WHERE id = ?',
                               (total_price, inventory_to_json(seller_inv), seller['id']))
                cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?',
                               (total_price, buyer['id']))
                cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?',
                               (inventory_to_json(buyer_inv), buyer['id']))
                # Mark fulfilled, update reputation
                cursor.execute('UPDATE agents SET total_contracts = total_contracts + 1, fulfilled_contracts = fulfilled_contracts + 1 WHERE id IN (?, ?)',
                               (seller['id'], buyer['id']))
                cursor.execute('UPDATE agents SET reputation = MIN(1.0, reputation + ?) WHERE id IN (?, ?)',
                               (contract['reputation_impact'], seller['id'], buyer['id']))
                status_reason = 'fulfilled'
                fulfilled = True
            else:
                status_reason = 'buyer_insufficient_funds'
        else:
            status_reason = 'seller_insufficient_goods'

        if not fulfilled:
            # Breach: penalize both parties but seller harder
            cursor.execute('UPDATE agents SET reputation = MAX(0, reputation - ?) WHERE id = ?',
                           (contract['reputation_impact'], seller['id']))
            cursor.execute('UPDATE agents SET reputation = MAX(0, reputation - ?) WHERE id = ?',
                           (contract['reputation_impact'] * 0.5, buyer['id']))
            cursor.execute('UPDATE agents SET total_contracts = total_contracts + 1 WHERE id IN (?, ?)',
                           (seller['id'], buyer['id']))
            # Breach fee: seller pays 25% of contract value as penalty to buyer
            breach_fee = total_price * 0.25
            if seller['balance'] >= breach_fee:
                cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (breach_fee, seller['id']))
                cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (breach_fee, buyer['id']))

        # Log contract execution
        cursor.execute('''
            INSERT INTO contract_log (contract_id, seller_id, buyer_id, good_name, quantity, total_price, status, tick)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (contract['id'], seller['id'], buyer['id'], contract['good_name'], contract['quantity'], total_price, status_reason, simulation['tick_count']))
        cursor.execute('UPDATE contracts SET status = ? WHERE id = ?',
                       ('completed_' + status_reason, contract['id']))
    conn.commit()


def agent_evaluate_reputation(conn, agent):
    """Periodically recalculate agent reputation based on contract record."""
    cursor = conn.cursor()
    cursor.execute('SELECT total_contracts, fulfilled_contracts, reputation FROM agents WHERE id = ?', (agent['id'],))
    row = cursor.fetchone()
    if not row or row['total_contracts'] == 0:
        return
    # Historical ratio-based reputation supplement
    ratio = row['fulfilled_contracts'] / row['total_contracts']
    # Blend: 70% behavioral ratio, 30% existing rep (smooths swings)
    new_rep = round(ratio * 0.7 + row['reputation'] * 0.3, 4)
    cursor.execute('UPDATE agents SET reputation = ? WHERE id = ?', (new_rep, agent['id']))


def update_reputations(conn):
    """Recalculate reputation for all agents who have completed contracts."""
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents WHERE total_contracts > 0')
    for agent in [dict(row) for row in cursor.fetchall()]:
        agent_evaluate_reputation(conn, agent)
    conn.commit()


def get_contracts_for_api(conn):
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, sa.name as seller_name, ba.name as buyer_name, ca.name as creator_name
        FROM contracts c
        JOIN agents sa ON c.seller_id = sa.id
        JOIN agents ba ON c.buyer_id = ba.id
        JOIN agents ca ON c.creator_id = ca.id
        ORDER BY c.id DESC
    ''')
    return [dict(row) for row in cursor.fetchall()]


def update_prices(conn):
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM market')
    goods = [dict(row) for row in cursor.fetchall()]
    for good in goods:
        new_price = price_from_supply_demand(
            good['supply'], good['demand'],
            good['base_price'], good['volatility'], good['elasticity']
        )
        cursor.execute('UPDATE market SET current_price = ?, updated_at = CURRENT_TIMESTAMP WHERE good_name = ?',
                       (new_price, good['good_name']))
    conn.commit()
    return goods


def record_history(conn):
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(balance) as total FROM agents')
    total_money = cursor.fetchone()['total'] or 0
    cursor.execute('SELECT * FROM agents')
    agents = [dict(row) for row in cursor.fetchall()]
    gini = calculate_gini(agents)
    cursor.execute('SELECT COUNT(*) as count FROM transactions')
    num_tx = cursor.fetchone()['count']
    cursor.execute('SELECT AVG(current_price) as avg FROM market')
    avg_price = cursor.fetchone()['avg'] or 0
    refined_goods = list(PRODUCTION_CHAINS.keys())
    total_refined = 0
    cursor.execute('SELECT inventory FROM agents')
    for row in cursor.fetchall():
        inv = parse_inventory(row['inventory'])
        for g in refined_goods:
            total_refined += inv.get(g, 0)
    cursor.execute('SELECT COUNT(*) as count FROM factories WHERE active = 1')
    factory_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM shops WHERE active = 1')
    shops_count = cursor.fetchone()['count']
    cursor.execute('SELECT avg_price FROM history ORDER BY tick DESC LIMIT 1')
    last = cursor.fetchone()
    last_avg = last['avg_price'] if last else avg_price
    inflation = ((avg_price - last_avg) / last_avg * 100) if last_avg > 0 else 0

    # Count processing_log entries in the last 10 ticks (rolling processing volume)
    cursor.execute('SELECT COUNT(*) as cnt FROM processing_log WHERE tick >= ?', (max(0, simulation['tick_count'] - 9),))
    processing_count = cursor.fetchone()['cnt'] or 0

    # Money flow: injection sources this tick
    # Shops selling finished goods: purchases by agents (shop cash increases)
    cursor.execute('SELECT COALESCE(SUM(ABS(amount)), 0) as tot FROM transactions WHERE transaction_type = ? AND tick >= ?', ('shop_sell', simulation['tick_count']))
    shop_sell_injection = cursor.fetchone()['tot'] or 0
    # Factory usage fees (money to mill owners)
    cursor.execute('SELECT COALESCE(SUM(fee_paid), 0) as tot FROM processing_log WHERE tick >= ?', (simulation['tick_count'],))
    factory_fee_injection = cursor.fetchone()['tot'] or 0
    # Mining fees
    cursor.execute('SELECT COALESCE(SUM(fee_paid), 0) as tot FROM mining_log WHERE tick >= ?', (simulation['tick_count'],))
    mining_fee_injection = cursor.fetchone()['tot'] or 0
    # Wealth redistribution: tax collected (removed from agents)
    cursor.execute('SELECT COUNT(*) as cnt FROM agents')
    num_agents = cursor.fetchone()['cnt'] or 1
    # We approximate injection as money added to agents via redistribution
    money_injected = shop_sell_injection + factory_fee_injection + mining_fee_injection

    # Money flow: sink sources this tick
    # Agent production costs
    cursor.execute('SELECT COALESCE(SUM(ABS(amount)), 0) as tot FROM transactions WHERE transaction_type = ? AND tick >= ?', ('production', simulation['tick_count']))
    prod_sink = cursor.fetchone()['tot'] or 0
    # Shop purchases from agents (shop cash outflow to buy refined goods)
    cursor.execute('SELECT COALESCE(SUM(ABS(amount)), 0) as tot FROM transactions WHERE transaction_type = ? AND tick >= ?', ('shop_buy', simulation['tick_count']))
    shop_buy_sink = cursor.fetchone()['tot'] or 0
    # Factory building costs
    cursor.execute('SELECT COALESCE(SUM(ABS(amount)), 0) as tot FROM transactions WHERE transaction_type = ? AND tick >= ?', ('factory_build', simulation['tick_count']))
    factory_build_sink = cursor.fetchone()['tot'] or 0
    # Consumption (inventory spend not going to another agent)
    money_sunk = prod_sink + shop_buy_sink + factory_build_sink

    cursor.execute('''
        INSERT INTO history (tick, total_money, gini_coefficient, num_transactions, avg_price, inflation_rate, total_refined, factories_active, shops_count, money_injected, money_sunk, processing_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (simulation['tick_count'], total_money, gini, num_tx, avg_price, inflation, total_refined, factory_count, shops_count, money_injected, money_sunk, processing_count))
    conn.commit()


def simulation_tick():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents')
    agents = [dict(row) for row in cursor.fetchall()]
    cursor.execute('SELECT * FROM market')
    market_goods = [dict(row) for row in cursor.fetchall()]
    if not agents or not market_goods:
        conn.close()
        return

    trigger_random_event(conn)

    # Dedicated shop opening mechanic: 5% chance per tick
    if random.random() < 0.05:
        apply_shop_opens(conn)

    # Consumer welfare boost: small income supplement to keep consumers solvent
    for agent in agents:
        if agent['agent_type'] == 'consumer' and agent['balance'] < 500:
            boost = min(100.0, 500.0 - agent['balance']) * 0.5
            cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (boost, agent['id']))

    for agent in agents:
        if agent['balance'] < MIN_BALANCE:
            cursor.execute('UPDATE agents SET balance = balance + 5 WHERE id = ?', (agent['id'],))
            cursor.execute('UPDATE agents SET happiness = MAX(0, happiness - 0.03) WHERE id = ?', (agent['id'],))
            continue

        if agent['agent_type'] == 'processor':
            actions = [('produce', 0.15), ('factory', 0.25), ('process', 0.10), ('sell_shop', 0.25), ('buy_shop', 0.10), ('consume', 0.05), ('trade', 0.05), ('build', 0.05), ('contract', 0.05)]
        elif agent['agent_type'] == 'producer':
            actions = [('produce', 0.35), ('factory', 0.10), ('process', 0.10), ('sell_shop', 0.25), ('buy_shop', 0.08), ('consume', 0.05), ('trade', 0.02), ('build', 0.05), ('contract', 0.05)]
        elif agent['agent_type'] == 'trader':
            actions = [('produce', 0.08), ('factory', 0.05), ('process', 0.05), ('sell_shop', 0.35), ('buy_shop', 0.12), ('consume', 0.10), ('trade', 0.20), ('build', 0.05), ('contract', 0.05)]
        else:
            actions = [('produce', 0.10), ('factory', 0.05), ('process', 0.05), ('sell_shop', 0.05), ('buy_shop', 0.20), ('consume', 0.35), ('trade', 0.10), ('build', 0.05), ('contract', 0.05)]

        action = random.choices([a[0] for a in actions], weights=[a[1] for a in actions])[0]

        if action == 'produce':
            agent_produce(conn, agent, market_goods)
        elif action == 'factory':
            agent_use_factory(conn, agent, market_goods)
        elif action == 'process':
            agent_process(conn, agent, market_goods)
        elif action == 'sell_shop':
            result = agent_sell_to_shop(conn, agent, market_goods)
            if not result:
                agent_sell_to_market(conn, agent, market_goods)
        elif action == 'buy_shop':
            agent_buy_from_shop(conn, agent, market_goods)
        elif action == 'consume':
            agent_consume(conn, agent, market_goods)
        elif action == 'build':
            result = agent_build_factory(conn, agent)
            if not result:
                agent_build_mine(conn, agent, market_goods)
        elif action == 'contract':
            agent_propose_contract(conn, agent, market_goods)
        else:
            agent_trade(conn, agent, market_goods)

    # Resolve matured contracts (deliveries due this tick)
    resolve_contracts(conn)

    # Periodic reputation recalculation (every 20 ticks)
    if simulation['tick_count'] % 20 == 0:
        update_reputations(conn)

    # Natural drift
    for good in market_goods:
        cursor.execute('''
            UPDATE market SET
                current_price = current_price + (base_price - current_price) * 0.012,
                supply = supply + (70 - supply) * 0.006,
                demand = demand + (70 - demand) * 0.006
            WHERE good_name = ?
        ''', (good['good_name'],))

    update_prices(conn)

    # === Shops use their dedicated mills to process raw materials into refined inputs ===
    cursor.execute('SELECT * FROM shops WHERE active = 1 AND mill_id IS NOT NULL')
    shop_mills = [dict(row) for row in cursor.fetchall()]
    for shop in shop_mills:
        if random.random() > 0.30:  # 70% chance per tick
            continue
        recipe = SHOP_RECIPES.get(shop['name'])
        if not recipe:
            continue
        # Get the mill's produces (e.g., 'Flour' for Bakery)
        cursor.execute('SELECT * FROM factories WHERE id = ? AND active = 1', (shop['mill_id'],))
        mill = cursor.fetchone()
        if not mill:
            continue
        refined_good = mill['produces']  # e.g. 'Flour'
        chain = PRODUCTION_CHAINS.get(refined_good)
        if not chain:
            continue
        # Check if mill has the raw inputs in the shop's inventory
        shop_inv_raw = shop['inventory'] or '{}'
        try:
            shop_inv = json.loads(shop_inv_raw)
        except:
            shop_inv = {}
        has_all = True
        for raw_good, needed in chain['inputs'].items():
            if shop_inv.get(raw_good, 0) < needed:
                has_all = False
                break
        if not has_all:
            continue
        # Consume raw inputs
        for raw_good, needed in chain['inputs'].items():
            shop_inv[raw_good] = shop_inv.get(raw_good, 0) - needed
            if shop_inv[raw_good] <= 0:
                del shop_inv[raw_good]
        # Produce refined output
        output_qty = chain['output_qty']
        efficiency = 0.85 + (mill['level'] * 0.12)
        output_qty = max(1, int(output_qty * efficiency))
        shop_inv[refined_good] = shop_inv.get(refined_good, 0) + output_qty
        cursor.execute('UPDATE shops SET inventory = ? WHERE id = ?',
                       (json.dumps(shop_inv), shop['id']))

    # Shops process inputs into outputs
    cursor.execute('SELECT * FROM shops WHERE active = 1')
    shops = [dict(row) for row in cursor.fetchall()]
    for shop in shops:
        recipe = SHOP_RECIPES.get(shop['name'])
        if not recipe:
            continue
        shop_inv_raw = shop['inventory'] or '{}'
        try:
            shop_inv = json.loads(shop_inv_raw)
        except:
            shop_inv = {}
        inputs = recipe['inputs']
        output = recipe['output']
        can_process = True
        for input_good, needed in inputs.items():
            if shop_inv.get(input_good, 0) < needed:
                can_process = False
                break
        if can_process:
            for input_good, needed in inputs.items():
                shop_inv[input_good] = shop_inv.get(input_good, 0) - needed
                if shop_inv[input_good] <= 0:
                    del shop_inv[input_good]
            output_qty = 1
            shop_inv[output] = shop_inv.get(output, 0) + output_qty
            cursor.execute('UPDATE shops SET inventory = ? WHERE id = ?',
                           (json.dumps(shop_inv), shop['id']))

    # Shops actively sell finished goods to agents (inject money into economy)
    for shop in shops:
        if random.random() > 0.30:  # 70% chance per shop per tick
            continue
        recipe = SHOP_RECIPES.get(shop['name'])
        if not recipe:
            continue
        shop_inv_raw = shop['inventory'] or '{}'
        try:
            shop_inv = json.loads(shop_inv_raw)
        except:
            shop_inv = {}
        output_good = recipe['output']
        if shop_inv.get(output_good, 0) <= 0:
            continue
        # Find an agent who can afford the shop's price
        cursor.execute('SELECT * FROM agents WHERE balance >= 10 ORDER BY RANDOM() LIMIT 3')
        candidates = [dict(row) for row in cursor.fetchall()]
        if not candidates:
            continue
        agent = candidates[0]
        shop_price = FINISHED_GOODS[output_good]['base_price'] * random.uniform(0.90, 1.05)
        qty = 1
        total = shop_price * qty
        if agent['balance'] < total:
            continue
        # Transfer goods and money
        shop_inv[output_good] = max(0, shop_inv.get(output_good, 0) - qty)
        cursor.execute('UPDATE shops SET inventory = ?, cash = cash + ? WHERE id = ?',
                       (json.dumps(shop_inv), total, shop['id']))
        agent_inv = parse_inventory(agent['inventory'])
        agent_inv[output_good] = agent_inv.get(output_good, 0) + qty
        cursor.execute('UPDATE agents SET inventory = ?, balance = balance - ? WHERE id = ?',
                       (inventory_to_json(agent_inv), total, agent['id']))
        happiness = FINISHED_GOODS[output_good]['happiness']
        cursor.execute('UPDATE agents SET happiness = MIN(1.0, happiness + ?) WHERE id = ?',
                       (happiness, agent['id']))
        tx_desc = '%s bought %dx %s from %s' % (agent['name'], qty, output_good, shop['name'])
        cursor.execute(
            'INSERT INTO transactions (from_agent, to_agent, amount, good_name, quantity, transaction_type, description, tick) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (agent['id'], -shop['id'], total, output_good, qty, 'shop_sell', tx_desc, simulation['tick_count']))
    if simulation['tick_count'] % 10 == 0:
        record_history(conn)

    # === Mines: Extract ore into the economy ===
    cursor.execute('SELECT * FROM mines WHERE active = 1')
    mines = cursor.fetchall()
    for mine in mines:
        if random.random() > 0.25:  # 75% chance to extract per tick
            continue
        mine_data = MINES.get(mine['name'], {})
        if not mine_data:
            continue
        output_good = mine_data['output']  # e.g. 'Iron'
        output_qty = random.randint(1, 3)
        fee = mine['fee_per_unit'] * output_qty
        # Find a customer (any agent with balance)
        cursor.execute('SELECT * FROM agents WHERE balance > ? ORDER BY RANDOM() LIMIT 1', (fee,))
        customer = cursor.fetchone()
        if not customer:
            continue
        # Deduct fee
        cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (fee, customer['id']))
        if mine['owner_id']:
            cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (fee, mine['owner_id']))
        # Add ore to customer inventory
        cursor.execute('SELECT inventory FROM agents WHERE id = ?', (customer['id'],))
        inv = parse_inventory(cursor.fetchone()['inventory'])
        inv[output_good] = inv.get(output_good, 0) + output_qty
        cursor.execute('UPDATE agents SET inventory = ? WHERE id = ?',
                       (inventory_to_json(inv), customer['id']))
        # Increase market supply
        cursor.execute('UPDATE market SET supply = supply + ? WHERE good_name = ?',
                       (output_qty, output_good))
        # Log it
        cursor.execute(
            'INSERT INTO mining_log (mine_id, customer_id, output_good, output_qty, fee_paid, tick) VALUES (?, ?, ?, ?, ?, ?)',
            (mine['id'], customer['id'], output_good, output_qty, fee, simulation['tick_count']))
    conn.commit()

    # === Wealth Redistribution: Tax + Minimum Guarantee ===
    # Only runs every WEALTH_REDIST_INTERVAL ticks to avoid smothering natural dynamics
    if simulation['tick_count'] % WEALTH_REDIST_INTERVAL == 0:
        cursor.execute('SELECT id, balance FROM agents')
        all_agents = cursor.fetchall()
        total_tax = 0.0
        for row in all_agents:
            if row['balance'] > WEALTH_TAX_THRESHOLD:
                tax = (row['balance'] - WEALTH_TAX_THRESHOLD) * WEALTH_TAX_RATE
                cursor.execute('UPDATE agents SET balance = balance - ? WHERE id = ?', (tax, row['id']))
                total_tax += tax

        # Step 2: Distribute collected tax equally to ALL agents (including rich, keeps it fair)
        if total_tax > 0:
            per_agent = total_tax / len(all_agents)
            for row in all_agents:
                cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (per_agent, row['id']))

        # Step 3: Minimum balance guarantee — top up any agent below threshold
        cursor.execute('SELECT id, balance FROM agents')
        broke_agents = [row for row in cursor.fetchall() if row['balance'] < WEALTH_MINIMUM]
        if broke_agents:
            total_topup = sum(WEALTH_MINIMUM - row['balance'] for row in broke_agents)
            cursor.execute('SELECT SUM(balance) as total FROM agents')
            economy_total = cursor.fetchone()['total'] or 0
            welfare_budget = economy_total * 0.05
            if total_topup > welfare_budget:
                per_broke = welfare_budget / len(broke_agents)
            else:
                per_broke = WEALTH_MINIMUM
            for row in broke_agents:
                shortfall = WEALTH_MINIMUM - row['balance']
                actual_topup = min(shortfall, per_broke)
                cursor.execute('UPDATE agents SET balance = balance + ? WHERE id = ?', (actual_topup, row['id']))

    simulation['tick_count'] += 1
    # set_state('tick_count', simulation['tick_count'])  # not essential, skip to avoid lock
    conn.close()


def simulation_loop():
    import traceback
    while simulation['running']:
        try:
            simulation_tick()
        except Exception as e:
            print('ERROR in simulation_tick:', e)
            traceback.print_exc()
        time.sleep(simulation['tick_interval'])
    print('simulation_loop exiting')


# ============ WEB ROUTES ============

@app.route('/')
def index():
    return send_file('/home/dalton/.openclaw/workspace/EconSim/templates/index.html', mimetype='text/html')

# ORIGINAL:
# def index():
#     conn = get_db()
#     cursor = conn.cursor()
#     cursor.execute('SELECT COUNT(*) as count FROM agents')
#     agent_count = cursor.fetchone()['count']
#     cursor.execute('SELECT SUM(balance) as total FROM agents')
#     total_money = cursor.fetchone()['total'] or 0
#     cursor.execute('SELECT COUNT(*) as count FROM transactions')
#     transaction_count = cursor.fetchone()['count']
#     cursor.execute('SELECT COUNT(*) as count FROM market')
#     market_items = cursor.fetchone()['count']
#     cursor.execute('SELECT COUNT(*) as count FROM factories WHERE active = 1')
#     factory_count = cursor.fetchone()['count']
#     cursor.execute('SELECT * FROM agents')
#     agents_data = [dict(row) for row in cursor.fetchall()]
#     gini = calculate_gini(agents_data)
#     conn.close()
#     return render_template('index.html',
#                            agent_count=agent_count,
#                            total_money=total_money,
#                            transaction_count=transaction_count,
#                            market_items=market_items,
#                            factories_active=factory_count,
#                            gini=gini,
#                            tick_count=simulation['tick_count'],
#                            sim_running=simulation['running'])


@app.route('/api/agents', methods=['GET'])
def get_agents():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents ORDER BY balance DESC')
    agents = [dict(row) for row in cursor.fetchall()]
    for a in agents:
        a['inventory'] = parse_inventory(a['inventory'])
    conn.close()
    return {'agents': agents}


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.*, f.name as from_name, t2.name as to_name
        FROM transactions t
        LEFT JOIN agents f ON t.from_agent = f.id
        LEFT JOIN agents t2 ON t.to_agent = t2.id
        ORDER BY t.id DESC LIMIT 100
    ''')
    transactions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {'transactions': transactions}


@app.route('/api/market', methods=['GET'])
def get_market():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM market ORDER BY is_refined, good_name')
    market = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {'market': market}


@app.route('/api/history', methods=['GET'])
def get_history():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM history ORDER BY tick DESC LIMIT 300')
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {'history': list(reversed(history))}


@app.route('/api/events', methods=['GET'])
def get_events():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM events ORDER BY id DESC LIMIT 20')
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {'events': events}


@app.route('/api/production_chains', methods=['GET'])
def get_production_chains():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT f.*, a.name as owner_name
        FROM factories f
        LEFT JOIN agents a ON f.owner_id = a.id
        WHERE f.active = 1
        ORDER BY f.produces, f.fee_per_unit
    ''')
    factories = [dict(row) for row in cursor.fetchall()]
    cursor.execute('''
        SELECT m.*, a.name as owner_name
        FROM mines m
        LEFT JOIN agents a ON m.owner_id = a.id
        WHERE m.active = 1
        ORDER BY m.name
    ''')
    mines = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {'chains': PRODUCTION_CHAINS, 'factories': factories, 'mines': mines}


@app.route('/api/factories', methods=['GET'])
def get_factories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT f.*, a.name as owner_name
        FROM factories f
        LEFT JOIN agents a ON f.owner_id = a.id
        ORDER BY f.produces, f.fee_per_unit
    ''')
    factories = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {'factories': factories}


@app.route('/api/shops', methods=['GET'])
def get_shops():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM shops WHERE active = 1 ORDER BY name')
    shops = [dict(row) for row in cursor.fetchall()]
    for s in shops:
        s['inventory'] = parse_inventory(s['inventory'])
    conn.close()
    return {'shops': shops}


@app.route('/api/contracts', methods=['GET'])
def get_contracts():
    conn = get_db()
    contracts = get_contracts_for_api(conn)
    conn.close()
    return {'contracts': contracts}


@app.route('/api/mines', methods=['GET'])
def get_mines():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.*, a.name as owner_name
        FROM mines m
        LEFT JOIN agents a ON m.owner_id = a.id
        ORDER BY m.name
    ''')
    mines = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {'mines': mines}


@app.route('/api/simulation/status', methods=['GET'])
def sim_status():
    return {
        'running': simulation['running'],
        'tick_count': simulation['tick_count'],
        'tick_interval': simulation['tick_interval']
    }


@app.route('/api/simulation/start', methods=['POST'])
def sim_start():
    if simulation['running']:
        return {'error': 'Already running'}, 400
    simulation['running'] = True
    simulation['thread'] = threading.Thread(target=simulation_loop, daemon=True)
    simulation['thread'].start()
    return {'status': 'started', 'tick_count': simulation['tick_count']}


@app.route('/api/simulation/stop', methods=['POST'])
def sim_stop():
    simulation['running'] = False
    return {'status': 'stopped', 'tick_count': simulation['tick_count']}


@app.route('/api/simulation/reset', methods=['POST'])
def sim_reset():
    simulation['running'] = False
    simulation['tick_count'] = 0
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM processing_log')
    cursor.execute('DELETE FROM factories')
    cursor.execute('DELETE FROM shops')
    cursor.execute('DELETE FROM mines')
    cursor.execute('DELETE FROM mining_log')
    cursor.execute('DELETE FROM transactions')
    cursor.execute('DELETE FROM history')
    cursor.execute('DELETE FROM events')
    # Re-insert seed agents with their proper starting balances
    cursor.execute('DELETE FROM agents')
    cursor.executemany(
        'INSERT INTO agents (name, agent_type, balance, inventory, happiness) VALUES (?,?,?,?,?)',
        [(n, t, b, json.dumps(i), 0.6) for n, t, b, i in INITIAL_AGENTS]
    )
    cursor.execute('UPDATE market SET supply = 70, demand = 70, current_price = base_price')
    conn.commit()
    conn.close()
    return {'status': 'reset'}


@app.route('/api/simulation/speed', methods=['POST'])
def sim_speed():
    data = request.json
    simulation['tick_interval'] = max(0.1, min(5.0, data.get('interval', 1.0)))
    return {'status': 'ok', 'tick_interval': simulation['tick_interval']}


if __name__ == '__main__':
    init_db()
    app.run(debug=False, port=5002)
