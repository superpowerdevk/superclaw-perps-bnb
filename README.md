# SuperClaw BNB Perps — Copy-Trade Skill

A SuperClaw skill that copy-trades a single, centrally-curated **BNB** perpetual agent on Hyperliquid onto **your own** account. Install it in SuperClaw, complete a short setup, and the skill mirrors the curated agent's BNB positions for you. You stay in control and can pause or stop anytime.

> ⚠️ **Real funds, real trades.** This software places live perpetual trades on Hyperliquid with leverage. You can lose some or all of your capital. Past performance of any agent does not guarantee future results. Never deposit more than you can afford to lose. This is beta software — verify behavior with a small amount first.

> 🔒 **Key safety.** Your generated agent-wallet key is stored locally in the per-instance config and is excluded from git by `.gitignore`. Never commit config files containing private keys.

## What it does

- Follows **one curated BNB agent** (selected centrally by SuperClaw — you do not pick the trader) and mirrors its position changes onto your Hyperliquid account.
- **Locked to BNB** — the skill only ever places BNB orders.
- Uses a **baseline + delta** alignment model (it submits the minimum order to stay aligned) rather than blindly replaying every fill.
- Runs on **your own dedicated Hyperliquid account**, funded with **USDC** — isolated from your other SuperClaw skills.
- Exposes the curated agent's **overall track record** on request (ROI, PnL, max profit, max drawdown, liquidations, win rate, strategy).

## How it works

1. On install, the skill generates a delegated **Agent Wallet** for you.
2. You authorize that Agent Wallet on Hyperliquid (Agent + Builder) from a **fresh wallet** funded with USDC.
3. The curated agent is resolved automatically from `active_agent.json` (the platform can update it for everyone by editing that pointer).
4. The service builds a baseline of the agent's positions, then keeps your account aligned via deltas as the agent trades.

The Agent Wallet is a **trade-only delegate** — it can place orders on your behalf but cannot withdraw your funds, and you can revoke it anytime on Hyperliquid.

## Setup (in SuperClaw — no terminal needed)

Install in your SuperClaw chat:

```
install https://github.com/superpowerdevk/superclaw-perps-bnb
```

The skill then walks you through 4 steps:

1. **Create a fresh wallet** — a brand-new wallet (OKX Wallet, MetaMask, or Phantom) used only for this skill, on the **Arbitrum** chain. Keep a little ETH on Arbitrum for gas. (Hyperliquid caps agents per account at ~3, so each skill needs its own wallet.)
2. **Fund it with USDC** — deposit USDC into that wallet's Hyperliquid account (USDC on Arbitrum or HyperEVM). Perps are USDC-margined — you never deposit BNB itself.
3. **Authorize trading** — open the authorize link with that wallet and sign **Agent + Builder** (no funds move, just permission).
4. **Send your wallet address** — reply with the address you used, and the skill starts copying BNB trades.

## What you can ask (in chat)

- `status` — running state, balance, current position
- `show my position` — your open BNB trade right now
- `how am I doing?` — your profit/loss summary
- `tell me about this agent` — the **curated agent's overall** track record (ROI, drawdown, win rate, strategy) — not your own history
- `set follow ratio to 50%` — copy at a fraction of the agent's size (lower = smaller, safer)
- `set stop loss to 20%` — auto-close a trade if it drops that much
- `show my settings` — current follow ratio, stop loss, slippage
- `pause` / `resume` / `stop` — control the service
- `update me every 15 minutes` — optional periodic position summaries (5 min · 15 min · 30 min · 1 hour · 4 hours · 12 hours · daily); `stop updates` to turn off

## Agent track record

`tell me about this agent` (or running `python3 agent_info.py`) fetches the curated agent's **overall** public metrics live from Moss and shows ROI, account PnL, max profit, **max drawdown**, blow-ups (liquidations), win rate, profit factor, trade count, and the strategy description. Drawdown and win rate are always shown next to ROI — this is informational, not investment advice.

## Configuration

The runnable project is a Python service (`follow_service/`) driven by `cli.py`; SuperClaw operates it for you. A per-instance config is generated under `~/.hyperliquid-copy-trade/<suffix>/config_<suffix>.json`. Key fields:

- `private_key` / `wallet_address` — the generated Agent Wallet (delegate signer)
- `main_address` — your funded Hyperliquid account
- `allowed_coins` — the skill's asset lock (this skill: **BNB** only)
- `agent_pointer_url` — remote pointer to the curated agent (`active_agent.json`)
- `follow_ratio`, `stop_loss_pct`, `slippage_percent` — risk/execution tuning
- `perp_dex` — set when the asset trades on a Hyperliquid builder DEX (e.g. commodities/equities like gold); the skill targets that market automatically

Generated config files contain a private key and are git-ignored — never commit them.

## Security

- The generated wallet is a **delegated trading agent**, not a funding wallet — it cannot withdraw.
- Keep your instance directory private; revoke Hyperliquid authorization if the agent wallet is no longer trusted.
- Use a dedicated wallet per skill — do not reuse a wallet across skills.

## Requirements

- Python 3.10+
- A Hyperliquid account funded with USDC
- Network access to `https://api.hyperliquid.xyz`, `https://ai.moss.site`, and the authorize page under `https://moss.site`

---

*SuperClaw — vertical agent identities with compounding loops. The followed agent is curated by the platform; you bear all trading risk.*
