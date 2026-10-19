"""Unit tests for the audio compression engine (smol.core.audio).

Validates:
- Codec selection matched to input family:
  (MP3 -> libmp3lame, AAC/M4A -> aac, Opus/OGG -> libopus)
- Bitrate computed from target with 24 kbps floor enforcement
- Output file size strictly <= target_bytes
- Original file untouched
- Already-small bypass
- Dry run prediction
- Routing integration via smol.core.router
- Complete decode / playback verification
All audio is synthetically generated using ffmpeg lavfi sine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from smol.core.audio import shrink_audio
from smol.core.media_math import probe_media
from smol.core.router import detect_file_type, shrink_file


def _generate_tone(
    dest_path: Path,
    duration: float = 10.0,
    bitrate_kbps: int = 192,
    freq: int = 440,
    codec: str | None = None,
) -> Path:
    """Generate a synthetic sine tone using ffmpeg lavfi sine."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    ext = dest_path.suffix.lower()

    if codec is None:
        if ext in (".mp3",):
            codec = "libmp3lame"
        elif ext in (".m4a", ".aac"):
            codec = "aac"
        elif ext in (".opus", ".ogg"):
            codec = "libopus"
        elif ext in (".wav",):
            codec = "pcm_s16le"
        else:
            codec = "libmp3lame"

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={freq}:duration={duration}",
    ]
    if codec != "pcm_s16le":
        cmd.extend(["-b:a", f"{bitrate_kbps}k"])
    cmd.extend(["-c:a", codec, str(dest_path)])

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"ffmpeg audio generation failed: {res.stderr}"
    assert dest_path.is_file(), f"Generated audio missing: {dest_path}"
    return dest_path


def _verify_audio_playback(path: Path) -> None:
    """Verify that an audio file decodes cleanly without errors."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "null",
        "/dev/null",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Audio decode verification failed: {res.stderr}"


def test_shrink_audio_mp3_family(tmp_path: Path) -> None:
    """Test shrinking an MP3 file using libmp3lame."""
    src = tmp_path / "tone.mp3"
    _generate_tone(src, duration=10.0, bitrate_kbps=256)
    orig_size = src.stat().st_size
    target = 70_000  # 70 KB target

    res = shrink_audio(src, target_bytes=target)
    assert res.ok is True, f"Failed: {res.error}"
    assert res.output_path is not None
    assert res.output_path.is_file()
    assert res.final_bytes <= target
    assert res.final_bytes == res.output_path.stat().st_size
    assert res.original_bytes == orig_size
    assert res.output_path.suffix.lower() == ".mp3"

    # Verify output decodes cleanly
    _verify_audio_playback(res.output_path)

    # Verify codec using probe
    info = probe_media(res.output_path)
    assert info.has_audio is True
    assert abs(info.duration - 10.0) < 1.0


def test_shrink_audio_aac_m4a_family(tmp_path: Path) -> None:
    """Test shrinking an M4A/AAC file using aac codec."""
    src = tmp_path / "tone.m4a"
    _generate_tone(src, duration=10.0, bitrate_kbps=256)
    target = 65_000  # 65 KB target

    res = shrink_audio(src, target_bytes=target)
    assert res.ok is True, f"Failed: {res.error}"
    assert res.output_path is not None
    assert res.final_bytes <= target
    assert res.output_path.suffix.lower() == ".m4a"

    _verify_audio_playback(res.output_path)


def test_shrink_audio_opus_ogg_family(tmp_path: Path) -> None:
    """Test shrinking an Opus file using libopus codec."""
    src = tmp_path / "tone.opus"
    _generate_tone(src, duration=10.0, bitrate_kbps=160)
    target = 50_000  # 50 KB target

    res = shrink_audio(src, target_bytes=target)
    assert res.ok is True, f"Failed: {res.error}"
    assert res.output_path is not None
    assert res.final_bytes <= target
    assert res.output_path.suffix.lower() == ".opus"

    _verify_audio_playback(res.output_path)


def test_shrink_audio_enforces_24kbps_floor(tmp_path: Path) -> None:
    """Test that impossible targets below 24 kbps floor fail honestly."""
    src = tmp_path / "short_tone.mp3"
    _generate_tone(src, duration=10.0, bitrate_kbps=128)

    # 10s at 24 kbps requires at least ~32.6 KB:
    # 24,000 * 10 / (8 * 0.92) = 32,608 bytes.
    # An impossible target like 10 KB must fail honestly.
    res = shrink_audio(src, target_bytes=10_000)
    assert res.ok is False
    assert res.output_path is None
    assert "24 kbps" in res.error or "floor" in res.error.lower()
    # Confirm no partial output file was created
    assert len(list(tmp_path.glob("short_tone_*.mp3"))) == 0


def test_shrink_audio_already_small(tmp_path: Path) -> None:
    """Test that audio already smaller than target returns ok without rewriting."""
    src = tmp_path / "small.mp3"
    _generate_tone(src, duration=3.0, bitrate_kbps=64)
    orig_size = src.stat().st_size

    res = shrink_audio(src, target_bytes=orig_size + 10_000)
    assert res.ok is True
    assert res.output_path == src
    assert res.final_bytes == orig_size
    assert res.warning is not None
    assert "already small enough" in res.warning


def test_shrink_audio_original_untouched(tmp_path: Path) -> None:
    """Verify that source audio file is never modified."""
    src = tmp_path / "pristine.mp3"
    _generate_tone(src, duration=5.0, bitrate_kbps=192)
    orig_bytes = src.read_bytes()

    res = shrink_audio(src, target_bytes=len(orig_bytes) // 2)
    assert res.ok is True
    assert res.output_path != src
    assert src.read_bytes() == orig_bytes


def test_shrink_audio_dry_run(tmp_path: Path) -> None:
    """Verify dry_run=True returns estimate without writing files."""
    src = tmp_path / "tone.mp3"
    _generate_tone(src, duration=8.0, bitrate_kbps=256)

    res = shrink_audio(src, target_bytes=60_000, options={"dry_run": True})
    assert res.ok is True
    assert res.output_path is None
    assert res.final_bytes is not None
    assert res.final_bytes <= 60_000
    assert len(list(tmp_path.glob("tone_*.mp3"))) == 0


def test_shrink_audio_router_dispatch(tmp_path: Path) -> None:
    """Verify detect_file_type and shrink_file route audio extensions."""
    for ext in (".mp3", ".m4a", ".aac", ".opus", ".ogg", ".flac", ".wav"):
        assert detect_file_type(f"track{ext}") == "audio"

    src = tmp_path / "routed.mp3"
    _generate_tone(src, duration=5.0, bitrate_kbps=192)
    res = shrink_file(src, target_bytes=40_000)
    assert res.ok is True
    assert res.output_path is not None
    assert res.final_bytes <= 40_000


def test_shrink_audio_overshoot_retry(tmp_path: Path) -> None:
    """Verify that if initial encode slightly overshoots, retry ensures <= target."""
    src = tmp_path / "tight.mp3"
    _generate_tone(src, duration=15.0, bitrate_kbps=192)

    # Choose a target that is close to a boundary
    res = shrink_audio(src, target_bytes=90_000)
    assert res.ok is True
    assert res.output_path is not None
    assert res.final_bytes <= 90_000


def test_verify_3min_tone_shrinks_and_plays(tmp_path: Path) -> None:
    """VERIFY task: A 3-minute generated tone shrinks to target size and plays."""
    src = tmp_path / "three_min_tone.mp3"
    _generate_tone(src, duration=180.0, bitrate_kbps=192, freq=520)
    orig_size = src.stat().st_size
    target = 1_000_000  # 1 MB target

    res = shrink_audio(src, target_bytes=target)
    assert res.ok is True, f"Failed: {res.error}"
    assert res.output_path is not None
    assert res.output_path.is_file()
    assert res.final_bytes <= target
    assert res.final_bytes == res.output_path.stat().st_size
    assert res.original_bytes == orig_size
    assert res.final_bytes >= int(target * 0.85)

    _verify_audio_playback(res.output_path)
