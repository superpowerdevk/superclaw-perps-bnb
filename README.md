> ⚠️ WARNING: This software executes real trades with real funds on Hyperliquid.
>
> - You can lose some or all of your capital. Past performance of any Moss agent does not guarantee future results.
> - This is beta software. There may be undiscovered bugs that could result in unexpected trades or losses.
> - Never deposit more than you can afford to lose into your trading account.
> - Your generated wallet's private key is stored locally. If compromised, your funds are at risk. Back it up securely and never commit it to version control.
> - This software is provided as-is with no warranty.  

> ⚠️ SECURITY: Never commit config files containing private keys to git.
>
> Generated config files (config_<suffix>.json) contain your wallet's private key. The included .gitignore excludes these by default. If you fork this repo, double-check that your private key is not exposed.



# Hyperliquid Copy Trade

A lightweight Python service for copy trading a Moss strategy on Hyperliquid.

The service watches a target Moss agent, builds a baseline snapshot of that agent's positions, and then keeps your Hyperliquid account aligned by applying position deltas instead of blindly replaying every fill.

## What this project does

- Tracks a Moss agent and mirrors position changes onto Hyperliquid
- Uses a baseline + delta alignment model to avoid naive per-fill copy trading
- Uses Moss WebSocket events as the primary signal channel, with REST polling as a fallback
- Stores baselines, events, trades, balance snapshots, and alerts in SQLite
- Runs as a background service with per-instance logs, PID files, and isolated state
- Supports low-balance alerts, balance snapshots, and optional stop-loss / take-profit checks

## Current limitations

- BTC is the only supported trading asset in the current implementation
- The service requires a dedicated generated trading wallet and a per-instance config file
- Every operational command must use an explicit `--config` file after wallet generation

## How it works

1. Generate an agent wallet.
2. Authorize that wallet on Hyperliquid from your main wallet.
3. Register the generated wallet as a Moss follower.
4. Point the config at a Moss `agent_id`.
5. Start the background service.
6. On startup, the service initializes a baseline from the target agent's current positions.
7. After that, incoming Moss events trigger delta-based position alignment on Hyperliquid.

The trading engine does not simply copy fills one by one. Instead, it compares:

- the agent's current position,
- the baseline position recorded at startup, and
- your current Hyperliquid position,

then submits the minimum order needed to bring your account back into alignment.

## Architecture

### Core modules

- `cli.py` - command-line entrypoint for configuration, service control, stats, and inspection
- `follow_service/main.py` - background service lifecycle, PID management, startup checks
- `follow_service/moss_ws.py` - primary Moss WebSocket event consumer
- `follow_service/moss_poller.py` - REST poller used as a backup signal path
- `follow_service/trader.py` - Hyperliquid execution, alignment logic, leverage handling, SL/TP helpers
- `follow_service/moss_client.py` - Moss REST client using follower wallet signatures
- `follow_service/database.py` - SQLite schema and data access helpers
- `follow_service/balance_tracker.py` - balance snapshots, low-balance alerts, periodic SL/TP checks
- `follow_service/preflight.py` - Hyperliquid Agent/Builder authorization checks
- `follow_service/config.py` - config validation, loading, and per-instance path management

### Runtime data

By default, each generated wallet gets its own state directory under:

```bash
~/.hyperliquid-copy-trade/<wallet_suffix>/
```

That instance directory contains:

- `config_<suffix>.json`
- `follow_agent.db`
- `service.pid`
- `logs/service.log`
- `logs/stdout.log`
- `logs/stderr.log`

You can override the base state directory with `FOLLOW_STATE_DIR`.

## Requirements

- Python 3.10+
- A Hyperliquid account with funds in the main account you want to trade from
- A Moss agent ID to follow
- Network access to:
  - `https://api.hyperliquid.xyz`
  - `https://ai.moss.site`
  - the authorization page under `https://moss.site`

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Quick start

### 1. Generate a wallet and instance config

```bash
.venv/bin/python cli.py config wallet-generate
```

This creates a new config file like:

```bash
~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json
```

Important notes:

- Do not use `config.json`
- Do not use `config_default.json`
- The code only accepts config files named `config_<last6>.json`
- After generation, use that config path in all commands

### 2. Set your main Hyperliquid account address

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  config set main_address 0xYOUR_MAIN_ADDRESS
```

`main_address` is the funded Hyperliquid account that actually owns the capital.

### 3. Authorize the generated wallet

Open the authorization page using the generated `wallet_address`:

```text
https://moss.site/hyperliquid/authorize/<wallet_address>
```

The service checks two permissions before trading:

- the generated wallet is authorized as an Agent for `main_address`
- the required Builder address is approved on Hyperliquid

Validate authorization with:

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  config check-auth
```

### 4. Configure the Moss agent to follow

Set the target `agent_id`:

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  config set moss_source.agent_id agt_xxx
```

Optional tuning examples:

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  config set follow_ratio 1.0

.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  config set slippage_percent 1.5

.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  config set alignment_loss_pct 3.0
```

### 5. Register the wallet as a Moss follower

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  moss register
```

This uses the generated wallet's private key to sign the Moss follower registration request.

### 6. Start the background service

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  service start
```

Check status:

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  service status
```

Stop it:

```bash
.venv/bin/python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json \
  service stop
```

## Configuration

The generated config is based on `config_default.json`.

Example:

```json
{
  "private_key": "",
  "wallet_address": "",
  "main_address": "",
  "allowed_coins": ["BTC"],
  "alignment_loss_pct": 3.0,
  "slippage_percent": 1.5,
  "follow_ratio": 1.0,
  "stop_loss_pct": 0,
  "take_profit_pct": 0,
  "sl_tp_interval": 10,
  "perp_only": true,
  "low_balance_threshold_usd": 10.0,
  "log_dir": "~/.hyperliquid-copy-trade/<suffix>/logs",
  "db_path": "~/.hyperliquid-copy-trade/<suffix>/follow_agent.db",
  "pid_file": "~/.hyperliquid-copy-trade/<suffix>/service.pid",
  "hl_api_url": "https://api.hyperliquid.xyz",
  "hl_authorize_url": "https://moss.site/hyperliquid/authorize",
  "moss_source": {
    "enabled": true,
    "base_url": "https://ai.moss.site",
    "agent_id": "",
    "fill_poll_secs": 15,
    "symbol_map": {
      "BTCUSDT": "BTC",
      "BTCUSDC": "BTC",
      "BTC-USDC": "BTC"
    },
    "agent_name": ""
  }
}
```

### Important config fields

- `private_key` - private key of the generated agent wallet
- `wallet_address` - generated wallet used for follower registration and Hyperliquid agent authorization
- `main_address` - funded Hyperliquid account to trade against
- `follow_ratio` - multiplier applied on top of the account-value ratio between you and the source agent
- `alignment_loss_pct` - startup deviation threshold; if exceeded, the service records a baseline but skips opening the initial catch-up position
- `slippage_percent` - price offset used when placing IOC limit orders
- `stop_loss_pct` / `take_profit_pct` - optional periodic close logic; disabled when set to `0`
- `low_balance_threshold_usd` - low-balance alert threshold; internally floored to the system minimum order threshold
- `moss_source.agent_id` - target Moss agent to follow
- `moss_source.fill_poll_secs` - REST polling interval for the fallback poller
- `allowed_coins` - currently forced to `['BTC']` by the service at startup

## CLI reference

### Service control

```bash
python cli.py --config <path> service start
python cli.py --config <path> service stop
python cli.py --config <path> service status
python cli.py --config <path> service pause
python cli.py --config <path> service resume
python cli.py --config <path> service switch
```

Behavior notes:

- `service pause` closes all positions, stops the service, and clears the baseline
- `service resume` restarts the service and rebuilds the baseline
- `service switch` pauses first, then prompts you to update `moss_source.agent_id`

### Configuration

```bash
python cli.py --config <path> config show
python cli.py --config <path> config set <key> <value>
python cli.py --config <path> config check-auth
python cli.py config wallet-generate
```

`config set` supports dotted keys such as `moss_source.agent_id` and tries to parse JSON values automatically.

Examples:

```bash
python cli.py --config <path> config set follow_ratio 0.5
python cli.py --config <path> config set perp_only true
python cli.py --config <path> config set allowed_coins '["BTC"]'
```

### Moss

```bash
python cli.py --config <path> moss register
```

### Baseline and inspection

```bash
python cli.py --config <path> baseline show
python cli.py --config <path> baseline reset
python cli.py --config <path> trades --limit 20
python cli.py --config <path> stats
python cli.py --config <path> dashboard
python cli.py --config <path> balance --limit 20
```

### Alerts

```bash
python cli.py --config <path> alerts list
python cli.py --config <path> alerts list --unread
python cli.py --config <path> alerts list --json
python cli.py --config <path> alerts ack <id>
python cli.py --config <path> alerts ack-all
```

## Database contents

The SQLite database stores:

- `agent_baseline` - per-agent baseline positions used for alignment
- `events` - Moss fill / source events, including sync status for de-duplication
- `trades` - local trade execution records with context and outcomes
- `account_snapshots` - periodic account value and withdrawable balance snapshots
- `alerts` - low-balance and other operational alerts

## Operational notes

- The service forks into the background on `service start`
- A PID file is written per instance, so multiple configs can run independently
- Logs are written with rotation to `logs/service.log`
- On startup, authorization is checked and logged, but startup is not blocked if the check fails
- The service uses both WebSocket events and REST polling to reduce missed updates
- Duplicate execution is mitigated with baseline locks, fill de-duplication, recent-event checks, and per-coin locks

## Security notes

- Generated config files contain a private key and are written with restrictive permissions when possible
- Keep the instance directory private and backed up appropriately
- The generated wallet is intended to act as a delegated trading agent, not as a funding wallet
- Revoke Hyperliquid authorization if the agent wallet is no longer trusted

## Troubleshooting

### Service says config is missing

Every command after wallet generation must include `--config <path>` unless you set `FOLLOW_CONFIG`.

### Service starts but does not trade

Check the following:

- `main_address` is set correctly
- the generated wallet has been authorized on Hyperliquid
- Builder authorization is approved
- `moss_source.enabled` is `true`
- `moss_source.agent_id` is set
- follower registration completed successfully with `moss register`

### Baseline exists but positions look wrong

Reset the baseline and restart the service:

```bash
python cli.py --config <path> baseline reset
python cli.py --config <path> service stop
python cli.py --config <path> service start
```

## Development notes

- There is currently no automated test suite in this repository
- `README.md` documents the current code path, which uses follower wallet signatures for Moss access
- `SKILL.md` contains conversation-flow notes for a higher-level skill wrapper, but the runnable project is the Python CLI and `follow_service/` package in this repository
