import re

_UNIT_FACTORS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 1_000,
    "kb": 1_000,
    "m": 1_000_000,
    "mb": 1_000_000,
    "g": 1_000_000_000,
    "gb": 1_000_000_000,
}

_SIZE_PATTERN = re.compile(
    r"^\s*([+-]?[0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)\s*$"
)


def parse_size(val: str | float) -> int:
    """Parse human size string or number into bytes.

    Uses decimal units (1 KB = 1000 bytes, 1 MB = 1,000,000 bytes).
    Examples:
        parse_size("100KB") -> 100000
        parse_size("1.5MB") -> 1500000
        parse_size("250000") -> 250000
        parse_size("100 kb") -> 100000
    """
    if val is None or isinstance(val, bool):
        raise TypeError(f"Invalid size type: {type(val).__name__}")

    if isinstance(val, (int, float)):
        if val <= 0:
            raise ValueError(f"Expected a positive size, got {val}")
        return round(val)

    if not isinstance(val, str):
        raise TypeError(f"Invalid size type: {type(val).__name__}")

    val_str = val.strip()
    if not val_str:
        raise ValueError("Expected a positive size, got empty string")

    match = _SIZE_PATTERN.match(val_str)
    if not match:
        raise ValueError(f"Cannot parse size: {val!r}")

    number_str, unit_str = match.groups()
    try:
        number = float(number_str)
    except ValueError as err:
        raise ValueError(f"Cannot parse numeric size value from {val!r}") from err

    if number <= 0:
        raise ValueError(f"Expected a positive size, got {number}")

    unit = unit_str.lower()
    if not unit:
        # Default unit is bytes
        multiplier = 1
    elif unit in _UNIT_FACTORS:
        multiplier = _UNIT_FACTORS[unit]
    else:
        raise ValueError(
            f"Unknown size unit {unit_str!r}. "
            "Supported units: B, KB, MB, GB (1 KB = 1000 bytes)"
        )

    return round(number * multiplier)


def format_size(target_bytes: int, spaced: bool = False) -> str:
    """Format bytes as human-readable string (1 KB = 1000 bytes).

    Examples:
        format_size(100000) -> "100KB"
        format_size(100000, spaced=True) -> "100 KB"
        format_size(1500000) -> "1.5MB"
        format_size(1500000, spaced=True) -> "1.5 MB"
    """
    sep = " " if spaced else ""
    if target_bytes >= 1_000_000_000:
        val = target_bytes / 1_000_000_000
        unit = "GB"
    elif target_bytes >= 1_000_000:
        val = target_bytes / 1_000_000
        unit = "MB"
    elif target_bytes >= 1_000:
        val = target_bytes / 1_000
        unit = "KB"
    else:
        return f"{target_bytes}{sep}B"

    # Format cleanly (e.g., 100 instead of 100.0, 1.5 instead of 1.50)
    formatted = f"{val:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}{sep}{unit}"
