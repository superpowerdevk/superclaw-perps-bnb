"""
启动前和下单前的授权校验。

检查项：
1. main_address 是否已将 wallet_address 授权为 Agent（extraAgents）
2. main_address 是否已授权 builder_address（approvedBuilders）
"""

import logging
import time

from . import config as cfg

logger = logging.getLogger("follow_agent.preflight")


def _post_info(api_url: str, payload: dict) -> list | dict:
    import requests

    r = requests.post(f"{api_url}/info", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def check_authorization(raise_on_fail: bool = True) -> bool:
    """
    校验主账号授权状态。

    Returns:
        True  — 全部授权通过
        False — 有授权缺失（raise_on_fail=False 时）

    Raises:
        RuntimeError — 授权缺失且 raise_on_fail=True
    """
    api_url = cfg.get("hl_api_url", "https://api.hyperliquid-testnet.xyz")
    main_address = cfg.get("main_address", "").lower()
    wallet_address = cfg.get("wallet_address", "").lower()
    builder_address = cfg.get_builder_address().lower()

    errors: list[str] = []
    if not main_address:
        msg = "main_address 未配置：请先配置主钱包地址。"
        logger.error(msg)
        errors.append(msg)
    if not wallet_address:
        msg = "wallet_address 未配置：请先生成 Agent Wallet。"
        logger.error(msg)
        errors.append(msg)
    if errors:
        if raise_on_fail:
            raise RuntimeError("授权校验失败:\n" + "\n".join(f"  - {e}" for e in errors))
        return False

    # ── 1. Agent 授权校验 ──────────────────────────────────────────────────
    # 优先用 userRole 查 wallet_address：role=="agent" 且 data.user==main_address
    # 若不满足，再回退查 extraAgents（兼容旧方式追加的 agent）
    if main_address and wallet_address:
        try:
            role_resp = _post_info(api_url, {"type": "userRole", "user": wallet_address})
            authorized = (
                role_resp.get("role") == "agent"
                and role_resp.get("data", {}).get("user", "").lower() == main_address
            )
            if not authorized:
                # 回退：extraAgents
                now_ms = int(time.time() * 1000)
                agents = _post_info(api_url, {"type": "extraAgents", "user": main_address})
                authorized = any(
                    a.get("address", "").lower() == wallet_address
                    and a.get("validUntil", 0) > now_ms
                    for a in agents
                )
            if authorized:
                logger.info("Agent auth OK: main=%s agent=%s", main_address[:10], wallet_address[:10])
            else:
                msg = (
                    f"Agent 未授权：主账号 {main_address} 尚未授权 {wallet_address} 为 Agent，"
                    "请在 Hyperliquid 页面完成 Agent 授权。"
                )
                logger.error(msg)
                errors.append(msg)
        except Exception as e:
            msg = f"Agent 授权查询失败: {e}"
            logger.error(msg)
            errors.append(msg)
    elif main_address or wallet_address:
        logger.warning("main_address 或 wallet_address 未配置，跳过 Agent 授权查询")

    # ── 2. Builder 授权校验 ────────────────────────────────────────────────
    if main_address and builder_address:
        try:
            approved = _post_info(api_url, {"type": "approvedBuilders", "user": main_address})
            authorized = any(b.lower() == builder_address for b in approved)
            if authorized:
                logger.info("Builder auth OK: main=%s builder=%s", main_address[:10], builder_address[:10])
            else:
                msg = (
                    f"Builder 未授权：主账号 {main_address} 尚未授权 builder {builder_address}，"
                    "请在 Hyperliquid 页面完成 Builder 授权。"
                )
                logger.error(msg)
                errors.append(msg)
        except Exception as e:
            msg = f"Builder 授权查询失败: {e}"
            logger.error(msg)
            errors.append(msg)
    else:
        if not builder_address:
            msg = "builder_address 未配置：无法校验 Builder 授权。"
            logger.error(msg)
            errors.append(msg)
        else:
            logger.warning("main_address 未配置，跳过 Builder 授权查询")

    if errors:
        if raise_on_fail:
            raise RuntimeError("授权校验失败:\n" + "\n".join(f"  - {e}" for e in errors))
        return False

    return True
