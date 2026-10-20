from pathlib import Path

from smol.core.suggest import (
    FloorEstimate,
    SuggestOptions,
    estimate_floor,
    suggest_sizes,
)


def test_classic_mode_defaults_and_order():
    """Classic mode returns default ladder in ascending order, never reshuffled."""
    options = SuggestOptions(mode="classic")
    # File is 1.2 MB (1_200_000 B), floor is 30 KB (30_000 B)
    suggestions = suggest_sizes(1_200_000, 30_000, "image", options)

    # All ladder entries are returned
    bytes_list = [s.bytes for s in suggestions]
    expected = [20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000]
    assert bytes_list == expected
    assert bytes_list == sorted(bytes_list)

    # 20 KB is below floor (30 KB)
    assert not suggestions[0].eligible
    assert suggestions[0].reason == "too small for this file (min about 30 KB)"
    assert suggestions[0].kind == "ladder"
    assert suggestions[0].label == "20 KB"

    # 50 KB through 1 MB are eligible
    for s in suggestions[1:6]:
        assert s.eligible
        assert s.reason is None
        assert s.kind == "ladder"

    # 2 MB is larger than original 1.2 MB
    assert not suggestions[6].eligible
    assert suggestions[6].reason == "larger than the file"


def test_classic_mode_12kb_input():
    """12 KB input in classic mode: all entries are larger than the file."""
    options = SuggestOptions(mode="classic")
    suggestions = suggest_sizes(12_000, 5_000, "image", options)

    assert len(suggestions) == 7
    for s in suggestions:
        assert not s.eligible
        assert s.reason == "larger than the file"


def test_classic_mode_floor_above_all():
    """Floor higher than all ladder rungs marks all ineligible with floor reason."""
    options = SuggestOptions(mode="classic")
    # File is 10 MB, but floor is 3 MB (above all default ladder entries up to 2 MB)
    suggestions = suggest_sizes(10_000_000, 3_000_000, "image", options)

    assert len(suggestions) == 7
    for s in suggestions:
        assert not s.eligible
        assert s.reason == "too small for this file (min about 3 MB)"


def test_classic_mode_ignores_pinned_and_recents():
    """Pinned and recents are NOT part of the ring in classic mode."""
    options = SuggestOptions(
        mode="classic",
        pinned=(75_000,),
        recents=(150_000,),
    )
    suggestions = suggest_sizes(1_200_000, 10_000, "image", options)
    bytes_list = [s.bytes for s in suggestions]
    assert 75_000 not in bytes_list
    assert 150_000 not in bytes_list
    assert all(s.kind == "ladder" for s in suggestions)


def test_classic_mode_near_duplicates_deduped():
    """Near-duplicates within 5% are deduped, keeping the larger."""
    options = SuggestOptions(
        mode="classic",
        ladder=(20_000, 98_000, 100_000, 200_000),  # 98 KB and 100 KB are within ~2%
    )
    suggestions = suggest_sizes(1_200_000, 10_000, "image", options)
    bytes_list = [s.bytes for s in suggestions]
    assert 98_000 not in bytes_list
    assert 100_000 in bytes_list
    assert bytes_list == [20_000, 100_000, 200_000]


def test_smart_mode_1_2mb_input():
    """1.2 MB input in smart mode gives 50, 100, 200, 500 KB and 1 MB."""
    options = SuggestOptions(mode="smart")
    # floor = 30 KB.
    # 0.9 * 1.2 MB = 1.08 MB.
    # floor * 1.05 = 31.5 KB.
    # Pool has: 20K (too small), 50K, 100K, 200K, 500K, 1M (eligible), 2M, 5M (too big).
    suggestions = suggest_sizes(1_200_000, 30_000, "image", options)
    bytes_list = [s.bytes for s in suggestions]
    assert bytes_list == [50_000, 100_000, 200_000, 500_000, 1_000_000]
    assert all(s.eligible for s in suggestions)
    assert all(s.reason is None for s in suggestions)


def test_smart_mode_12kb_input_gives_no_ladder_entries():
    """12 KB input in smart mode gives no ladder entries (relative fallbacks)."""
    options = SuggestOptions(mode="smart")
    # Floor 10 KB: 10 * 1.05 = 10.5 KB.
    # 0.9 * 12 KB = 10.8 KB.
    # No pool entry fits. Relative 12 KB * 0.75 = 9 KB (< 10.5 KB).
    # Nothing is eligible -> returns empty list.
    suggestions = suggest_sizes(12_000, 10_000, "image", options)
    assert suggestions == []

    # Floor 2 KB: relative fallbacks can be eligible
    suggestions_low_floor = suggest_sizes(12_000, 2_000, "image", options)
    # No ladder entries in result!
    assert all(s.kind != "ladder" for s in suggestions_low_floor)
    assert all(s.kind == "relative" for s in suggestions_low_floor)
    bytes_list = [s.bytes for s in suggestions_low_floor]
    # 12K * 0.75 = 9K -> 5K; 12K * 0.5 = 6K -> 5K (deduped); 12K * 0.25 = 3K -> 2.5K
    assert bytes_list == [2_500, 5_000]


def test_smart_mode_30kb_input_relative_addition():
    """30 KB input in smart mode adds relative rungs when fewer than 3 fit."""
    options = SuggestOptions(mode="smart")
    # floor = 3 KB. floor * 1.05 = 3.15 KB.
    # 0.9 * 30 KB = 27 KB.
    # Pool has 20 KB. (count 1 < 3).
    # Relatives:
    # 30 KB * 0.75 = 22.5 KB -> nice 20 KB (matches existing 20 KB, within 5%, skipped)
    # 30 KB * 0.5 = 15 KB -> nice 10 KB (added)
    # 30 KB * 0.25 = 7.5 KB -> nice 5 KB (added)
    suggestions = suggest_sizes(30_000, 3_000, "image", options)
    bytes_list = [s.bytes for s in suggestions]
    assert bytes_list == [5_000, 10_000, 20_000]
    kinds = {s.bytes: s.kind for s in suggestions}
    assert kinds[20_000] == "ladder"
    assert kinds[10_000] == "relative"
    assert kinds[5_000] == "relative"


def test_smart_mode_40mb_input_log_spacing():
    """40 MB input in smart mode: 8 pool entries fit, capped to 6 on log scale."""
    options = SuggestOptions(mode="smart", max_segments=6)
    # floor = 10 KB
    suggestions = suggest_sizes(40_000_000, 10_000, "image", options)
    assert len(suggestions) == 6
    bytes_list = [s.bytes for s in suggestions]
    # Spaced on log scale: 20K, 50K, 200K, 500K, 2M, 5M
    assert bytes_list == [20_000, 50_000, 200_000, 500_000, 2_000_000, 5_000_000]


def test_smart_mode_pinned_and_recent_merging():
    """Pinned and recents join pool in smart mode under same eligibility rules."""
    options = SuggestOptions(
        mode="smart",
        pinned=(150_000,),
        recents=(300_000,),
    )
    # 1.2 MB file, floor 30 KB
    suggestions = suggest_sizes(1_200_000, 30_000, "image", options)
    bytes_list = [s.bytes for s in suggestions]
    assert 150_000 in bytes_list
    assert 300_000 in bytes_list
    kinds = {s.bytes: s.kind for s in suggestions}
    assert kinds[150_000] == "pinned"
    assert kinds[300_000] == "recent"


def test_smart_mode_floor_above_all_returns_empty():
    """Smart mode returns empty list when floor is above all candidates."""
    options = SuggestOptions(mode="smart")
    suggestions = suggest_sizes(5_000_000, 3_000_000, "image", options)
    assert suggestions == []


def test_smart_mode_near_duplicates_deduped():
    """Smart mode dedupes candidates within 5%, keeping larger."""
    options = SuggestOptions(
        mode="smart",
        pinned=(98_000,),  # 98K is within 2% of pool 100K
    )
    suggestions = suggest_sizes(1_200_000, 30_000, "image", options)
    bytes_list = [s.bytes for s in suggestions]
    assert 98_000 not in bytes_list
    assert 100_000 in bytes_list


def test_determinism():
    """Identical parameters produce identical results on repeated calls."""
    options = SuggestOptions(
        mode="smart",
        pinned=(150_000, 350_000),
        recents=(75_000,),
    )
    run1 = suggest_sizes(2_500_000, 40_000, "image", options)
    run2 = suggest_sizes(2_500_000, 40_000, "image", options)
    assert run1 == run2

    options_classic = SuggestOptions(mode="classic")
    c1 = suggest_sizes(1_200_000, 30_000, "image", options_classic)
    c2 = suggest_sizes(1_200_000, 30_000, "image", options_classic)
    assert c1 == c2


def test_estimate_floor_image(samples_dir: Path):
    """estimate_floor for image does fast probe encode downscaled to min_dim, q60."""
    sample_img = samples_dir / "portrait.jpg"
    est = estimate_floor(sample_img)
    assert isinstance(est, FloorEstimate)
    assert est.source == "predicted"
    assert est.bytes > 0
    # Downscaled to 200px short side at q60 is typically around a few KB (< 25 KB)
    assert est.bytes < 30_000


def test_estimate_floor_pdf(samples_dir: Path):
    """estimate_floor for PDF returns conservative heuristic with source='estimate'."""
    pdf_path = samples_dir / "sample_scanned.pdf"
    est = estimate_floor(pdf_path)
    assert isinstance(est, FloorEstimate)
    assert est.source == "estimate"
    assert est.bytes > 0
    assert est.bytes < pdf_path.stat().st_size
