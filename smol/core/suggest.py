"""Size suggestion engine and fast floor estimation for smol.

Pure Python module with zero Qt dependencies and zero configuration imports.
Provides size suggestions for the Donut UI in two modes:
- CLASSIC (default): Fixed ladder in ascending order with honest eligibility reasons.
- SMART (opt-in): Dynamically selected target sizes within file boundaries,
  spaced evenly on a log scale, with relative fallbacks when few pool items fit.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from smol.core.size import format_size

DEFAULT_LADDER: tuple[int, ...] = (
    20_000,
    50_000,
    100_000,
    200_000,
    500_000,
    1_000_000,
    2_000_000,
)

DEFAULT_POOL: tuple[int, ...] = (
    20_000,
    50_000,
    100_000,
    200_000,
    500_000,
    1_000_000,
    2_000_000,
    5_000_000,
)

ANCHORS: frozenset[int] = frozenset(
    {
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
    }
)


@dataclass
class SuggestOptions:
    """Options governing size suggestions."""

    mode: str = "classic"
    ladder: tuple[int, ...] = DEFAULT_LADDER
    pool: tuple[int, ...] = DEFAULT_POOL
    pinned: Sequence[int] = ()
    recents: Sequence[int] = ()
    max_segments: int = 6
    min_dim: int = 200


@dataclass(frozen=True)
class SizeSuggestion:
    """A single suggested target size for the donut ring or CLI."""

    bytes: int
    label: str
    kind: str  # "ladder" | "relative" | "pinned" | "recent"
    eligible: bool
    reason: str | None = None


@dataclass(frozen=True)
class FloorEstimate:
    """Estimate of the lowest achievable compressed size."""

    bytes: int
    source: str  # "predicted" | "estimate"


@dataclass
class _Candidate:
    bytes: int
    kind: str


def _is_within_5_percent(a: int, b: int) -> bool:
    """Check if two sizes are within 5% of each other."""
    if a == b:
        return True
    return abs(a - b) <= 0.05 * max(a, b) + 1e-9


def _dedupe_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    """Deduplicate candidates within 5%, keeping the larger size."""
    if not candidates:
        return []

    kind_prio = {"relative": 0, "ladder": 1, "recent": 2, "pinned": 3}
    # Sort ascending by bytes, and by kind priority
    sorted_cands = sorted(candidates, key=lambda c: (c.bytes, kind_prio.get(c.kind, 0)))

    result = [sorted_cands[-1]]
    for c in reversed(sorted_cands[:-1]):
        top = result[-1]
        if _is_within_5_percent(c.bytes, top.bytes):
            if (
                top.bytes == c.bytes
                and kind_prio.get(c.kind, 0) > kind_prio.get(top.kind, 0)
            ):
                result[-1] = c
            continue
        result.append(c)

    result.reverse()
    return result


def _round_down_nice(val: float) -> int:
    """Round down to 1, 2, 2.5, or 5 times a power of ten."""
    if val <= 0:
        return 0

    exp = math.floor(math.log10(val))
    base = 10**exp
    for mult in (5.0, 2.5, 2.0, 1.0):
        cand = round(mult * base)
        if cand <= val:
            return cand
    return round(base)


def _select_log_spaced(candidates: list[_Candidate], max_k: int) -> list[_Candidate]:
    """Select at most max_k candidates spaced roughly evenly on a log scale.

    Tie-breaking: prefer anchors (100 KB, 200 KB, 500 KB, 1 MB, 2 MB),
    then prefer larger values.
    """
    n = len(candidates)
    if n <= max_k:
        return candidates
    if max_k <= 0:
        return []
    if max_k == 1:
        return [candidates[0]]

    log_vals = [math.log(c.bytes) for c in candidates]
    log_min = log_vals[0]
    log_max = log_vals[-1]
    targets = [log_min + j * (log_max - log_min) / (max_k - 1) for j in range(max_k)]

    # Dynamic programming: find indices 0 = i_0 < i_1 < ... < i_{max_k - 1} = n - 1
    # matching targets 0 .. max_k - 1 minimizing distance and respecting tie rules.
    dp: list[dict[int, tuple[float, int, int, int]]] = [{} for _ in range(max_k)]

    dp[0][0] = (
        0.0,
        -1 if candidates[0].bytes in ANCHORS else 0,
        -candidates[0].bytes,
        -1,
    )

    for j in range(1, max_k):
        target = targets[j]
        i_min = j
        i_max = n - 1 if j == max_k - 1 else n - (max_k - j)

        for i in range(i_min, i_max + 1):
            dist = round(abs(log_vals[i] - target), 9)
            is_anchor = -1 if candidates[i].bytes in ANCHORS else 0
            val_tie = -candidates[i].bytes

            best_prev = None
            best_prev_idx = -1
            for prev_i in range(j - 1, i):
                if prev_i in dp[j - 1]:
                    prev_cost, prev_anc, prev_val, _ = dp[j - 1][prev_i]
                    candidate_cost = (
                        prev_cost + dist,
                        prev_anc + is_anchor,
                        prev_val + val_tie,
                    )
                    if best_prev is None or candidate_cost < best_prev:
                        best_prev = candidate_cost
                        best_prev_idx = prev_i

            if best_prev is not None:
                dp[j][i] = (
                    best_prev[0],
                    best_prev[1],
                    best_prev[2],
                    best_prev_idx,
                )

    # Backtrack path
    curr = n - 1
    res_indices = [curr]
    for j in range(max_k - 1, 0, -1):
        curr = dp[j][curr][3]
        res_indices.append(curr)
    res_indices.reverse()

    return [candidates[i] for i in res_indices]


def suggest_sizes(
    original_bytes: int,
    floor_bytes: int,
    file_type: str = "image",
    options: SuggestOptions | None = None,
) -> list[SizeSuggestion]:
    """Suggest target sizes for compression.

    Args:
        original_bytes: Original file size in bytes.
        floor_bytes: Smallest achievable size in bytes.
        file_type: Type of file (e.g. "image", "pdf").
        options: Configuration options (SuggestOptions).

    Returns:
        List of SizeSuggestion objects.
    """
    opts = options or SuggestOptions()
    mode = (opts.mode or "classic").lower().strip()

    if mode == "classic":
        # Dedupe ladder entries within 5% (keep the larger)
        raw_candidates = [_Candidate(bytes=b, kind="ladder") for b in opts.ladder]
        deduped = _dedupe_candidates(raw_candidates)

        suggestions: list[SizeSuggestion] = []
        for cand in deduped:
            b = cand.bytes
            if b > original_bytes:
                eligible = False
                reason = "larger than the file"
            elif b < floor_bytes:
                eligible = False
                formatted_floor = format_size(floor_bytes, spaced=True)
                reason = f"too small for this file (min about {formatted_floor})"
            else:
                eligible = True
                reason = None

            suggestions.append(
                SizeSuggestion(
                    bytes=b,
                    label=format_size(b, spaced=True),
                    kind=cand.kind,
                    eligible=eligible,
                    reason=reason,
                )
            )
        return suggestions

    elif mode == "smart":
        # Gather all candidates from pool, pinned, and recents
        candidates: list[_Candidate] = []
        for b in opts.pool:
            candidates.append(_Candidate(bytes=b, kind="ladder"))
        for b in opts.pinned:
            candidates.append(_Candidate(bytes=b, kind="pinned"))
        for b in opts.recents:
            candidates.append(_Candidate(bytes=b, kind="recent"))

        # Dedupe entries within 5% (keep the larger)
        deduped = _dedupe_candidates(candidates)

        # Filter by eligibility: floor * 1.05 <= size <= 0.9 * original
        min_allowed = floor_bytes * 1.05
        max_allowed = original_bytes * 0.9
        eligible = [c for c in deduped if min_allowed <= c.bytes <= max_allowed]

        # If fewer than 3 are eligible, add relative rungs
        if len(eligible) < 3:
            for frac in (0.75, 0.5, 0.25):
                raw_rel = original_bytes * frac
                nice_rel = _round_down_nice(raw_rel)
                if min_allowed <= nice_rel <= max_allowed and not any(
                    _is_within_5_percent(nice_rel, e.bytes) for e in eligible
                ):
                    eligible.append(_Candidate(bytes=nice_rel, kind="relative"))
                    # Re-sort to maintain order
                    eligible.sort(key=lambda c: c.bytes)

        # If still nothing is eligible, return empty list
        if not eligible:
            return []

        # If more than max_segments are eligible, keep max_segments spaced on log scale
        if len(eligible) > opts.max_segments:
            eligible = _select_log_spaced(eligible, opts.max_segments)

        return [
            SizeSuggestion(
                bytes=c.bytes,
                label=format_size(c.bytes, spaced=True),
                kind=c.kind,
                eligible=True,
                reason=None,
            )
            for c in eligible
        ]

    else:
        raise ValueError(f"Unknown suggest mode: {opts.mode!r}")


def estimate_floor(
    src: str | Path,
    options: SuggestOptions | dict[str, Any] | None = None,
) -> FloorEstimate:
    """Estimate the minimum achievable size for a given file.

    For images: performs a fast probe encode (downscale to min_dim, quality 60).
    For PDFs: returns a conservative heuristic (e.g. 20% of original size).
    """
    src_path = Path(src)
    if not src_path.is_file():
        raise FileNotFoundError(f"File not found: {src_path}")

    ext = src_path.suffix.lower()
    file_size = src_path.stat().st_size

    if ext == ".pdf":
        # Conservative heuristic: 20% of file size, minimum 10 KB
        est_bytes = max(10_000, int(file_size * 0.20))
        return FloorEstimate(bytes=est_bytes, source="estimate")

    # Images
    min_dim = 200
    if options is not None:
        if isinstance(options, dict):
            min_dim = options.get("min_dim", 200)
        else:
            min_dim = getattr(options, "min_dim", 200)

    try:
        with Image.open(src_path) as raw_img:
            img = ImageOps.exif_transpose(raw_img)
            if img is None:
                img = raw_img.copy()

            w, h = img.size
            if min(w, h) > min_dim:
                scale = min_dim / min(w, h)
                new_w = max(1, round(w * scale))
                new_h = max(1, round(h * scale))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            if ext == ".webp":
                img.save(buf, format="WEBP", quality=60)
            else:
                # Flatten alpha if needed for JPEG probe
                if img.mode in ("RGBA", "LA") or (
                    img.mode == "P" and "transparency" in img.info
                ):
                    rgba = img.convert("RGBA")
                    white_bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    white_bg.paste(rgba, mask=rgba.split()[3])
                    img = white_bg
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=60, optimize=True)

            return FloorEstimate(bytes=len(buf.getvalue()), source="predicted")
    except (OSError, ValueError, Image.DecompressionBombError):
        # Fallback if image probe decode fails or decompression bomb is encountered
        return FloorEstimate(
            bytes=max(5_000, int(file_size * 0.15)),
            source="estimate",
        )
