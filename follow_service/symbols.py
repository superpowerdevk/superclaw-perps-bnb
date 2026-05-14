"""Symbol normalization helpers shared by Moss consumers."""

_QUOTE_SUFFIXES = ("USDT", "USDC")


def symbol_to_coin(symbol: str, symbol_map: dict | None = None) -> str | None:
    """Map Moss symbols to Hyperliquid coin names using config plus quote suffix fallback."""
    if not symbol:
        return None

    symbol_map = symbol_map or {}
    if symbol in symbol_map:
        return symbol_map[symbol]

    normalized = symbol.replace("-", "")
    if normalized in symbol_map:
        return symbol_map[normalized]

    for quote in _QUOTE_SUFFIXES:
        if normalized.endswith(quote):
            return normalized[:-len(quote)]
    return None
