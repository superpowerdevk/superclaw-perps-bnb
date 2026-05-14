#!/usr/bin/env python3
"""
Hyperliquid Copy Trade — command-line interface.

Usage:
    python cli.py [--config <path>] service start
    python cli.py [--config <path>] service stop
    python cli.py [--config <path>] service status

    python cli.py [--config <path>] config show
    python cli.py [--config <path>] config set <key> <value>

    python cli.py [--config <path>] baseline show
    python cli.py [--config <path>] baseline reset

    python cli.py [--config <path>] trades [--limit N] [--agent <address>]
    python cli.py [--config <path>] stats
    python cli.py [--config <path>] balance [--limit N]

Multi-instance:
    python cli.py --config ~/.hyperliquid-copy-trade/f4c4cb/config_f4c4cb.json service start
    python cli.py --config ~/.hyperliquid-copy-trade/ee8867/config_ee8867.json service start
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))

from follow_service import config as cfg
from follow_service import database as db


# ─── helpers ──────────────────────────────────────────────────────────────────

def _run_service(cmd: str) -> None:
    env = os.environ.copy()
    config_path = cfg.get_config_path()
    env["FOLLOW_CONFIG"] = str(config_path.resolve())
    subprocess.run(
        [sys.executable, "-m", "follow_service.main", cmd,
         "--config", str(config_path.resolve())],
        cwd=Path(__file__).parent,
        env=env,
    )


def _print_table(rows: list[dict], keys: list[str]) -> None:
    if not rows:
        print("(no records)")
        return
    widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    header = "  ".join(k.ljust(widths[k]) for k in keys)
    print(header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys))


# ─── commands ─────────────────────────────────────────────────────────────────

def cmd_service(args: list[str]) -> None:
    if not args:
        print("Usage: service <start|stop|status|pause|resume|switch>")
        return
    subcmd = args[0]
    if subcmd == "pause":
        cmd_service_pause()
    elif subcmd == "resume":
        cmd_service_resume()
    elif subcmd == "switch":
        cmd_service_switch()
    else:
        _run_service(subcmd)


def cmd_service_pause() -> None:
    """暂停跟单：全平仓 + 停服务 + 清基线。"""
    from follow_service.trader import close_all_positions

    db.init_db()

    # 1. 全平仓
    print("正在平仓所有持仓...")
    results = close_all_positions()
    if results:
        for r in results:
            pnl_str = f"pnl=${r['pnl']:.2f}" if r['pnl'] is not None else "pnl=N/A"
            print(f"  {r['coin']} {r['side']} size={r['size']:.6f} status={r['status']} {pnl_str}")
    else:
        print("  无持仓需要平仓")

    # 2. 停服务
    print("正在停止服务...")
    _run_service("stop")

    # 3. 清基线
    moss_cfg = cfg.get_moss_source_config()
    agent_id = moss_cfg.get("agent_id", "")
    if agent_id:
        db.clear_baselines(agent_id)
        print(f"已清除 Moss 基线: {agent_id}")

    print(f"跟单已暂停。使用 'python cli.py --config {cfg.get_config_path()} service resume' 恢复。")


def cmd_service_resume() -> None:
    """恢复跟单：启动服务（自动重建基线）。"""
    print("正在恢复跟单...")
    _run_service("start")
    print("服务已启动，基线将自动重建。")


def cmd_service_switch() -> None:
    """切换 Agent：暂停 + 提示配置新 agent_id。"""
    cmd_service_pause()
    print()
    print("请配置新的 Agent:")
    print(f"  方式 1: 编辑 {cfg.get_config_path()} 中 moss_source.agent_id")
    print(f"  方式 2: python cli.py --config {cfg.get_config_path()} config set moss_source '{{...}}'")
    print()
    print(f"配置完成后，运行 'python cli.py --config {cfg.get_config_path()} service resume' 恢复跟单。")


def cmd_check_auth() -> None:
    """校验主账号的 Agent 和 Builder 授权状态。"""
    from follow_service.preflight import check_authorization
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ok = check_authorization(raise_on_fail=False)
    if ok:
        print("授权校验通过：Agent 和 Builder 均已授权。")
    else:
        print("授权校验失败，请查看上方错误信息。")


def cmd_wallet_generate() -> None:
    """生成新的以太坊钱包，自动创建 config_<6位>.json 文件。"""
    from eth_account import Account

    acct = Account.create()
    private_key = acct.key.hex()
    wallet_address = acct.address
    suffix = wallet_address[-6:].lower()
    config_name = f"config_{suffix}.json"
    state_dir = cfg.get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        state_dir.chmod(0o700)
    except OSError:
        pass
    instance_dir = state_dir / suffix
    instance_dir.mkdir(parents=True, exist_ok=True)
    try:
        instance_dir.chmod(0o700)
    except OSError:
        pass
    config_path = instance_dir / config_name

    # 检查文件是否已存在
    if config_path.exists():
        confirm = input(
            f"{config_name} 已存在，覆盖将丢失原有配置。确认覆盖？(yes/N): "
        ).strip().lower()
        if confirm != "yes":
            print("已取消。")
            return

    # 从 config_default.json 加载模板
    default_path = Path(__file__).parent / "config_default.json"
    if not default_path.exists():
        print(f"ERROR: 模板文件不存在: {default_path}")
        return

    with open(default_path) as f:
        config_data = json.load(f)

    # 写入钱包信息
    config_data["private_key"] = private_key
    config_data["wallet_address"] = wallet_address

    # 自动设置实例隔离路径
    config_data["log_dir"] = str(instance_dir / "logs")
    config_data["db_path"] = str(instance_dir / "follow_agent.db")
    config_data["pid_file"] = str(instance_dir / "service.pid")

    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)
    try:
        config_path.chmod(0o600)
    except OSError:
        pass

    print(f"新钱包已生成并写入 {config_path}：")
    print(f"  wallet_address : {wallet_address}")
    print(f"  private_key    : {private_key[:6]}...{private_key[-4:]} (已保存)")
    print()
    print("网络配置：")
    print(f"  Hyperliquid API : {config_data['hl_api_url']}")
    print(f"  Moss API        : {config_data['moss_source']['base_url']}")
    print()
    print("后续步骤：")
    print("  1. 用主账号在 Hyperliquid 页面对该地址授权 Agent 和 Builder")
    print(f"  2. 运行 '.venv/bin/python cli.py --config {config_path} config check-auth' 验证授权")
    print(f"  3. 运行 '.venv/bin/python cli.py --config {config_path} moss register' 注册 Follower")
    print("  4. 配置 moss_source 后启动服务")
    print()
    print("授权页面：")
    print(f"  {config_data['hl_authorize_url']}/{wallet_address}")
    if config_data.get("moss_agent_list_url"):
        print("Moss Agent 列表：")
        print(f"  {config_data['moss_agent_list_url']}")


def cmd_config_show() -> None:
    c = cfg.load_config()
    # Mask private key
    display = {**c}
    if display.get("private_key"):
        pk = display["private_key"]
        display["private_key"] = pk[:6] + "..." + pk[-4:] if len(pk) > 10 else "***"
    print(json.dumps(display, indent=2))


def cmd_config_set(args: list[str]) -> None:
    if len(args) < 2:
        print("Usage: config set <key> <value>")
        return
    key, value = args[0], args[1]

    # 优先按 JSON 解析：int/float/bool/null/list/dict 自动得到原生类型；
    # 解析失败（如 0x 开头的地址、纯字符串 private_key 等）则保留为字符串。
    # 覆盖原有的显式数值 coercion（json.loads("3")==3, json.loads("1.5")==1.5）
    # 并修复 dict/list 类型（如 moss_source、allowed_coins）被当字符串存储的 bug。
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        parsed = value

    cfg.set_value(key, parsed)
    print(f"Set {key} = {parsed!r}")


def cmd_baseline_show() -> None:
    """展示当前基线快照状态。"""
    db.init_db()
    moss_cfg = cfg.get_moss_source_config()
    agent_address = moss_cfg.get("agent_id", "")
    if not agent_address:
        print("No moss_source.agent_id configured.")
        return
    rows = db.get_baselines_list(agent_address)
    if not rows:
        print(f"No baseline found for {agent_address}.")
        print("Baseline is initialized on service start.")
        return
    print(f"Baseline for agent: {agent_address}")
    print()
    keys = ["coin", "baseline_agent_size", "our_baseline_size", "init_pnl_pct", "opened_at_init", "created_at"]
    _print_table(rows, keys)


def cmd_baseline_reset() -> None:
    """清除基线，下次服务启动时将重新初始化。"""
    moss_cfg = cfg.get_moss_source_config()
    agent_address = moss_cfg.get("agent_id", "")
    if not agent_address:
        print("No moss_source.agent_id configured.")
        return
    print(f"Clearing baseline for {agent_address}...")
    db.init_db()
    db.clear_baselines(agent_address)
    print("Baseline cleared. It will be re-initialized on next service start.")
    print(
        "Restart the service: "
        f"python cli.py --config {cfg.get_config_path()} service stop && "
        f"python cli.py --config {cfg.get_config_path()} service start"
    )


def cmd_trades(args: list[str]) -> None:
    db.init_db()
    limit = 20
    agent_address = None
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--agent" and i + 1 < len(args):
            agent_address = args[i + 1]
            i += 2
        else:
            i += 1

    trades = db.get_trades(agent_address=agent_address, limit=limit)
    keys = ["id", "source", "coin", "side", "our_size", "our_usd", "ref_price",
            "filled_price", "leverage", "status", "agent_delta", "baseline_agent_size", "created_at"]
    _print_table(trades, keys)


def cmd_stats() -> None:
    db.init_db()

    # Agent 名称
    moss_cfg = cfg.get_moss_source_config()
    agent_name = moss_cfg.get("agent_name", "")
    if not agent_name and moss_cfg.get("agent_id"):
        try:
            from follow_service.moss_client import MossClient
            client = MossClient(
                base_url=moss_cfg.get("base_url", ""),
                agent_id=moss_cfg["agent_id"],
            )
            info = client.get_agent_info()
            agent_data = info.get("bot", {})
            agent_name = agent_data.get("name", "")
            if agent_name:
                ms = dict(moss_cfg)
                ms["agent_name"] = agent_name
                cfg.set_value("moss_source", ms)
        except Exception:
            pass

    if agent_name:
        print(f"  agent: {agent_name} ({moss_cfg.get('agent_id', '')})")
    elif moss_cfg.get("agent_id"):
        print(f"  agent: {moss_cfg['agent_id']}")

    # 全量统计
    stats = db.get_trade_stats()
    print("--- 全量 ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # 今日统计
    today = db.get_today_stats()
    print("--- 今日 ---")
    for k, v in today.items():
        print(f"  {k}: {v}")


def cmd_dashboard() -> None:
    """展示完整的 Agent 数据看板。"""
    from follow_service.trader import get_current_positions
    import subprocess

    db.init_db()

    # 1. 账户概览
    print("=" * 60)
    print("Agent 数据看板")
    print("=" * 60)

    wallet_address = cfg.get("wallet_address", "")
    main_address = cfg.get("main_address") or wallet_address
    if wallet_address:
        masked = wallet_address[:6] + "..." + wallet_address[-4:]
        print(f"\nAgent 钱包地址: {masked}")

    # 服务状态
    try:
        env = os.environ.copy()
        env["FOLLOW_CONFIG"] = str(cfg.get_config_path().resolve())
        result = subprocess.run(
            [sys.executable, "-m", "follow_service.main", "status",
             "--config", str(cfg.get_config_path().resolve())],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            env=env,
        )
        stdout = result.stdout.lower()
        if result.returncode != 0:
            status = "未知"
        elif "running" in stdout:
            status = "运行中"
        elif "stopped" in stdout:
            status = "已暂停"
        else:
            status = "未知"
    except Exception:
        status = "未知"
    print(f"当前跟单状态: {status}")

    # 账户余额
    try:
        pos_data = get_current_positions(main_address)
        account_value = pos_data["account_value"]
        withdrawable = pos_data["withdrawable"]
        positions = pos_data["positions"]
        print(f"跟单资金总额: {account_value:.2f} USDC")
        print(f"可用余额: {withdrawable:.2f} USDC")
    except Exception as e:
        print(f"无法获取账户余额: {e}")
        account_value = 0
        withdrawable = 0
        positions = {}

    # 2. 今日 P&L
    print("\n" + "-" * 60)
    print("今日 P&L")
    print("-" * 60)

    today_stats = db.get_today_stats()
    today_fee = db.get_today_fee()
    print(f"今日盈亏: {today_stats['today_pnl']:.4f} USDC ({today_stats['today_pnl_pct']:+.2f}%)")
    print(f"今日手续费: {today_fee:.4f} USDC")

    # 已实现 / 未实现盈亏
    total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions.values())
    print(f"已实现盈亏（今日）: {today_stats['today_pnl']:.4f} USDC")
    print(f"未实现盈亏（当前持仓）: {total_unrealized:.4f} USDC")

    # 3. 当前持仓
    if positions:
        print("\n" + "-" * 60)
        print("当前持仓")
        print("-" * 60)
        for coin, pos in positions.items():
            side = "做多" if pos["size"] > 0 else "做空"
            print(f"{coin} {side} | 仓位: {abs(pos['size']):.6f} | 开仓价: {pos['entry_px']:.2f} | 杠杆: {pos['leverage']}x | 未实现盈亏: {pos['unrealized_pnl']:.4f} USDC")
    else:
        print("\n当前无持仓")

    # 4. 近期交易记录（最近 5 条）
    print("\n" + "-" * 60)
    print("近期交易记录（最近 5 条）")
    print("-" * 60)

    recent_trades = db.get_recent_trades_with_status(limit=5)
    if recent_trades:
        for t in recent_trades:
            time_str = t["created_at"][:19].replace("T", " ")
            side_str = "做多" if t["side"] == "buy" else "做空"
            pnl_str = f"{t['realized_pnl']:.4f}" if t.get("realized_pnl") is not None else "N/A"
            leverage_str = f"{t['leverage']}x" if t.get('leverage') else "N/A"
            print(
                f"{time_str} | {t['coin']} {side_str} | "
                f"开仓价: {t['filled_price']:.2f} | 仓位: {t['our_size']:.6f} | "
                f"杠杆: {leverage_str} | 盈亏: {pnl_str} | {t['position_status']}"
            )
    else:
        print("暂无交易记录")

    # 5. 跟单绩效汇总
    print("\n" + "-" * 60)
    print("跟单绩效汇总")
    print("-" * 60)

    stats = db.get_trade_stats()
    print(f"总盈亏: {stats['total_realized_pnl']:.4f} USDC")
    print(f"总胜率: {stats['win_rate']:.1f}%")
    print(f"跟单天数: {stats['trading_days']} 天")
    print(f"累计交易笔数: {stats['filled']} 笔")

    # Agent 信息
    moss_cfg = cfg.get_moss_source_config()
    agent_name = moss_cfg.get("agent_name", "")
    if agent_name:
        print(f"\n当前跟单 Agent: {agent_name}")
    elif moss_cfg.get("agent_id"):
        print(f"\n当前跟单 Agent: {moss_cfg['agent_id']}")

    print("\n" + "=" * 60)


def cmd_balance(args: list[str]) -> None:
    db.init_db()
    limit = 20
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            i += 1
    rows = db.get_account_snapshots(limit=limit)
    _print_table(rows, ["id", "account_value", "withdrawable", "created_at"])


def cmd_alerts_list(args: list[str]) -> None:
    db.init_db()
    unread_only = "--unread" in args
    as_json = "--json" in args
    limit = 50
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            i += 1

    if unread_only:
        rows = db.get_unread_alerts()[:limit]
    else:
        rows = db.get_recent_alerts(limit=limit)

    if as_json:
        # payload 已是 JSON 字符串，反序列化为对象
        out = []
        for r in rows:
            item = dict(r)
            if isinstance(item.get("payload"), str):
                try:
                    item["payload"] = json.loads(item["payload"])
                except json.JSONDecodeError:
                    pass
            out.append(item)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if not rows:
        print("(no alerts)")
        return
    keys = ["id", "type", "alert_date", "acknowledged", "created_at", "payload"]
    _print_table(rows, keys)


def cmd_alerts_ack(args: list[str]) -> None:
    db.init_db()
    if not args:
        print("Usage: alerts ack <id> [<id> ...]")
        return
    ids = [int(x) for x in args]
    n = db.mark_alerts_acknowledged(ids)
    print(f"已标记 {n} 条为已读。")


def cmd_alerts_ack_all() -> None:
    db.init_db()
    n = db.mark_all_alerts_acknowledged()
    print(f"已标记全部 {n} 条为已读。")


def cmd_moss_register() -> None:
    """注册为 Moss follower（钱包签名鉴权）。"""
    from follow_service.moss_client import MossClient

    moss_cfg = cfg.get_moss_source_config()
    base_url = moss_cfg.get("base_url", "")
    agent_id = moss_cfg.get("agent_id", "")
    private_key = cfg.get("private_key", "")
    wallet_address = cfg.get("wallet_address", "")
    main_address = cfg.get("main_address", "")
    builder_address = cfg.get_builder_address()

    if not base_url:
        print("ERROR: moss_source.base_url not configured")
        return
    if not private_key:
        print("ERROR: private_key not configured")
        return

    client = MossClient(
        base_url=base_url, agent_id=agent_id,
        private_key=private_key, wallet_address=wallet_address,
        main_address=main_address,
        builder_address=builder_address,
    )

    print(f"Registering follower: wallet={client._wallet_address} main={client._main_address}")
    try:
        result = client.register_follower()
        print(f"OK: follower_id={result.get('follower_id')} status={result.get('status')}")
    except Exception as e:
        print(f"ERROR: {e}")


# ─── main dispatcher ──────────────────────────────────────────────────────────

USAGE = """
Hyperliquid Copy Trade CLI

Usage: python cli.py [--config <path>] <command> [args]

Global options:
  --config <path>                       Use a specific config file (multi-instance)

Commands:
  service start                         Start background service
  service stop                          Stop background service
  service status                        Check service status
  service pause                         Pause: close all positions + stop service
  service resume                        Resume: restart service (rebuild baseline)
  service switch                        Switch Agent: pause + prompt for new agent_id
  moss register                         Register as Moss follower (wallet signature)
  alerts list [--unread] [--json] [--limit N]
                                        List balance/system alerts
  alerts ack <id> [<id> ...]            Mark specific alerts as read
  alerts ack-all                        Mark all alerts as read
  config show                           Show current configuration
  config set <key> <value>              Set a config value
  config check-auth                     Check Agent and Builder authorization status
  config wallet-generate                Generate a new wallet (private_key + wallet_address)
  baseline show                         Show current baseline snapshot
  baseline reset                        Clear baseline (re-initialized on next start)
  trades [--limit N] [--agent ADDR]       Show trade history
  stats                                 Show aggregate statistics
  dashboard                             Show full Agent dashboard
  balance [--limit N]                   Show account balance snapshots
"""


def main() -> None:
    argv = sys.argv[1:]

    # 解析全局 --config 参数
    if len(argv) >= 2 and argv[0] == "--config":
        config_path = Path(argv[1])
        if not config_path.exists():
            print(f"ERROR: config file not found: {config_path}")
            sys.exit(1)
        cfg.set_config_path(config_path)
        argv = argv[2:]

    if not argv:
        print(USAGE)
        return

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "service":
        cmd_service(rest)
    elif cmd == "config":
        if not rest:
            cmd_config_show()
        elif rest[0] == "show":
            cmd_config_show()
        elif rest[0] == "set":
            cmd_config_set(rest[1:])
        elif rest[0] == "wallet-generate":
            cmd_wallet_generate()
        elif rest[0] == "check-auth":
            cmd_check_auth()
        else:
            print(f"Unknown config subcommand: {rest[0]}")
    elif cmd == "moss":
        if not rest or rest[0] == "register":
            cmd_moss_register()
        else:
            print(f"Unknown moss subcommand: {rest[0]}")
            print("Usage: moss register")
    elif cmd == "alerts":
        if not rest or rest[0] == "list":
            cmd_alerts_list(rest[1:])
        elif rest[0] == "ack":
            cmd_alerts_ack(rest[1:])
        elif rest[0] == "ack-all":
            cmd_alerts_ack_all()
        else:
            print(f"Unknown alerts subcommand: {rest[0]}")
            print("Usage: alerts <list|ack <id>...|ack-all>")
    elif cmd == "baseline":
        if not rest or rest[0] == "show":
            cmd_baseline_show()
        elif rest[0] == "reset":
            cmd_baseline_reset()
        else:
            print(f"Unknown baseline subcommand: {rest[0]}")
            print("Usage: baseline <show|reset>")
    elif cmd == "trades":
        cmd_trades(rest)
    elif cmd == "stats":
        cmd_stats()
    elif cmd == "dashboard":
        cmd_dashboard()
    elif cmd == "balance":
        cmd_balance(rest)
    else:
        print(USAGE)


if __name__ == "__main__":
    main()
