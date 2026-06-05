"""
Background service entry point — Coinpilot 仓位对齐模式

Usage:
    python -m follow_service.main start
    python -m follow_service.main stop
    python -m follow_service.main status
"""

import asyncio
import os
import signal
import sys
import threading
from pathlib import Path

from . import config as cfg
from . import database as db
from . import hyper_coins
from .logger_setup import setup_logger
from .balance_tracker import run_balance_tracker, run_sltp_checker
from .hyper_coins import run_hyper_coin_refresher
from .moss_poller import run_moss_poller
from .moss_reporter import run_moss_reporter
from .moss_ws import run_moss_ws
from .preflight import check_authorization


logger = setup_logger()


def _pid_file() -> Path:
    return Path(cfg.get("pid_file", str(cfg.get_instance_dir() / "service.pid"))).expanduser()


def _read_pid() -> int | None:
    p = _pid_file()
    if p.exists():
        try:
            return int(p.read_text().strip())
        except ValueError:
            pass
    return None


def _write_pid(pid: int) -> None:
    p = _pid_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(pid))


def _remove_pid(pid: int | None = None) -> None:
    """只删除指定 PID 的文件；默认删除当前进程 PID，避免误删新服务。"""
    p = _pid_file()
    expected_pid = str(pid if pid is not None else os.getpid())
    try:
        if p.exists() and p.read_text().strip() == expected_pid:
            p.unlink()
    except (FileNotFoundError, ValueError):
        pass


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def cmd_status() -> None:
    instance_id = cfg.get_instance_id()
    pid = _read_pid()
    if pid and _is_running(pid):
        print(f"running (pid={pid}, instance={instance_id})")
    else:
        _remove_pid(pid)
        print(f"stopped (instance={instance_id})")
    auth_ok = check_authorization(raise_on_fail=False)
    print(f"authorization={'ok' if auth_ok else 'failed'}")


def cmd_stop() -> None:
    pid = _read_pid()
    if not pid or not _is_running(pid):
        print("Service is not running.")
        _remove_pid(pid)
        return
    os.kill(pid, signal.SIGTERM)
    print(f"Sent SIGTERM to pid {pid}")


def cmd_start() -> None:
    instance_id = cfg.get_instance_id()
    config_path = cfg.get_config_path()
    logger.info("Starting instance=%s config=%s", instance_id, config_path)

    pid = _read_pid()
    if pid and _is_running(pid):
        print(f"Service already running (pid={pid}, instance={instance_id})")
        return

    # Validate config
    private_key = cfg.get("private_key", "")
    if not private_key:
        print("ERROR: private_key is not set. Run: python cli.py config set private_key <KEY>")
        sys.exit(1)

    cfg.ensure_dirs()
    db.init_db()

    try:
        from .agent_pointer import sync_agent_pointer
        sync_agent_pointer()
    except Exception as exc:
        print(f"WARNING: agent pointer sync failed: {exc}")

    if cfg.get("require_subaccount", False):
        _sub = str(cfg.get("subaccount_address", "") or "").strip()
        if not _sub:
            try:
                from .subaccount import ensure_subaccount
                _sub = ensure_subaccount()
            except Exception as exc:
                print(f"WARNING: sub-account create failed: {exc}")
                _sub = None
            if not _sub:
                from .subaccount import guidance_text
                print(guidance_text())
                sys.exit(1)

    raw_moss_cfg = cfg.get("moss_source", {})
    legacy_bot_id = (
        isinstance(raw_moss_cfg, dict)
        and not raw_moss_cfg.get("agent_id")
        and raw_moss_cfg.get("bot_id")
    )
    moss_cfg = cfg.get_moss_source_config(migrate_bot_id=True)
    if legacy_bot_id:
        print("WARNING: migrated legacy moss_source.bot_id to moss_source.agent_id")

    if moss_cfg.get("enabled"):
        base_url = moss_cfg.get("base_url", "")
        agent_id = moss_cfg.get("agent_id", "")
        if not all([base_url, agent_id]):
            print("ERROR: moss_source.enabled=true requires moss_source.base_url and moss_source.agent_id")
            print("Set agent_id first, e.g.: python cli.py --config <config> config set moss_source.agent_id agt_xxx")
            sys.exit(1)

    # allowed_coins 仅保留为兼容旧配置；跟单限制改为 Hyperliquid 支持币种缓存。
    allowed = cfg.get("allowed_coins", [])
    if allowed:
        logger.info("allowed_coins is ignored for trade filtering; Hyper coin cache is authoritative")
    else:
        logger.info("allowed_coins is empty; Hyper coin cache is authoritative")

    # Fail fast: 未授权时启动只会持续下单失败，直接阻塞启动并让用户先修配置/授权。
    if not check_authorization(raise_on_fail=False):
        logger.error("Service startup aborted: authorization check failed")
        print("ERROR: authorization check failed. Run `config check-auth` and complete Agent/Builder authorization first.")
        sys.exit(1)

    try:
        coin_cache = hyper_coins.refresh_supported_coins(force=True)
        if not coin_cache.get("coins"):
            raise RuntimeError("empty Hyperliquid supported coin list")
    except Exception as e:
        logger.error("Service startup aborted: cannot refresh Hyper coin cache: %s", e)
        print("ERROR: 无法获取 Hyperliquid 支持币种列表，请检查网络或 hl_api_url，服务未启动。")
        sys.exit(1)

    # Fork to background
    child_pid = os.fork()
    if child_pid > 0:
        _write_pid(child_pid)
        print(f"Service started (pid={child_pid}, instance={instance_id})")
        print(f"Config: {config_path}")
        print(f"Logs: {cfg.get('log_dir')}/service.log")
        return

    # --- child process ---
    os.setsid()
    _write_pid(os.getpid())

    # Redirect stdio
    log_dir = Path(cfg.get("log_dir", str(cfg.get_instance_dir() / "logs"))).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = open(log_dir / "stdout.log", "a")
    sys.stderr = open(log_dir / "stderr.log", "a")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_event = asyncio.Event()
    _running_tasks: list[asyncio.Task] = []

    def _handle_sigterm(*_):
        logger.info("Received SIGTERM, shutting down ...")
        stop_event.set()
        for t in _running_tasks:
            t.cancel()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    logger.info("Hyperliquid Copy Trade service starting (pid=%s)", os.getpid())

    async def _run_all() -> None:
        logger.info("Starting services ...")

        coros = [
            run_hyper_coin_refresher(stop_event),
            run_balance_tracker(stop_event),
            run_sltp_checker(stop_event),
        ]

        # Moss 信号源：WS（主通道）+ REST 轮询（补充通道）同时运行
        if moss_cfg.get("enabled"):
            logger.info("Moss source enabled, starting WS + poller ...")
            baseline_lock = threading.Lock()  # 防止两通道重复初始化基线
            coros.append(run_moss_reporter(stop_event))                # 写接口: heartbeat + trades batch
            coros.append(run_moss_ws(stop_event, baseline_lock))       # 主通道: WebSocket 实时事件
            coros.append(run_moss_poller(stop_event, baseline_lock))    # 补充通道: REST 轮询兜底

        for c in coros:
            _running_tasks.append(asyncio.create_task(c))

        await asyncio.gather(*_running_tasks, return_exceptions=True)

    try:
        loop.run_until_complete(_run_all())
    finally:
        _remove_pid()
        loop.close()
        logger.info("Service exited cleanly.")


def main() -> None:
    # 解析 --config 参数（由 cli.py 传入，用于在 ps 中区分多实例）
    args = sys.argv[1:]
    if "--config" in args:
        idx = args.index("--config")
        config_path = args[idx + 1]
        cfg.set_config_path(config_path)
        del args[idx:idx + 2]

    cmd = args[0] if args else "status"
    if cmd == "start":
        cmd_start()
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}. Use: start | stop | status")
        sys.exit(1)


if __name__ == "__main__":
    main()
