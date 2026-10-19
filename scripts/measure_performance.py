"""Performance measurement script for smol daemon and donut overlay.

Measures:
1. Time from trigger to donut visible (target < 150 ms)
2. Cold start time-to-first-pixel (very first use)
3. Warm summon latency (subsequent uses)
4. Idle CPU of the running daemon (target ~0%)
5. Idle memory usage of the running daemon (RSS)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def measure_daemon_resources(
    pid: int, sample_duration: float = 5.0
) -> dict[str, float]:
    """Sample /proc/[pid]/stat and /proc/[pid]/status to measure CPU% and memory."""
    stat_path = Path(f"/proc/{pid}/stat")
    status_path = Path(f"/proc/{pid}/status")

    if not stat_path.exists():
        raise ProcessLookupError(f"PID {pid} does not exist in /proc")

    clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

    def get_ticks() -> int:
        with open(stat_path) as f:
            fields = f.read().split()
            # utime is 14th field (index 13), stime is 15th field (index 14)
            return int(fields[13]) + int(fields[14])

    # Initial sample
    t0_time = time.perf_counter()
    t0_ticks = get_ticks()

    time.sleep(sample_duration)

    t1_time = time.perf_counter()
    t1_ticks = get_ticks()

    dt = t1_time - t0_time
    d_ticks = t1_ticks - t0_ticks

    cpu_seconds = d_ticks / clk_tck
    cpu_percent = (cpu_seconds / dt) * 100.0

    # Memory from /proc/[pid]/status
    rss_kb = 0
    vmsize_kb = 0
    with open(status_path) as f:
        for line in f:
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
            elif line.startswith("VmSize:"):
                vmsize_kb = int(line.split()[1])

    return {
        "pid": pid,
        "sample_duration_s": dt,
        "cpu_percent": cpu_percent,
        "rss_mb": rss_kb / 1024.0,
        "vmsize_mb": vmsize_kb / 1024.0,
    }


def measure_donut_latencies() -> dict[str, float]:
    """Measure cold-start, warm-start, and breakdown of summon-to-paint latency."""
    from PySide6.QtWidgets import QApplication

    from smol.ui.donut_window import DonutWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])

    results = {}

    # 1. Cold start measurement (without pre-building hidden)
    t_init_start = time.perf_counter()
    w_cold = DonutWindow(files=[])
    t_init_end = time.perf_counter()
    results["cold_init_ms"] = (t_init_end - t_init_start) * 1000.0

    painted_cold = False
    paint_cold_time = 0.0

    orig_paint_cold = w_cold.paintEvent

    def on_cold_paint(event):
        nonlocal painted_cold, paint_cold_time
        orig_paint_cold(event)
        if not painted_cold:
            painted_cold = True
            paint_cold_time = time.perf_counter()

    w_cold.paintEvent = on_cold_paint

    t_summon_cold = time.perf_counter()
    w_cold.center_at(400, 400)
    w_cold.capture_desktop_background()
    w_cold.show()

    timeout = time.perf_counter() + 2.0
    while not painted_cold and time.perf_counter() < timeout:
        app.processEvents()

    if not painted_cold:
        paint_cold_time = time.perf_counter()

    results["cold_summon_to_first_pixel_ms"] = (
        paint_cold_time - t_summon_cold
    ) * 1000.0
    results["cold_total_time_ms"] = (paint_cold_time - t_init_start) * 1000.0

    w_cold.hide()
    app.processEvents()
    w_cold.deleteLater()
    app.processEvents()

    # 2. First use on a window pre-built hidden (as done by daemon at startup)
    w_prebuilt = DonutWindow(files=[])
    w_prebuilt.show()
    app.processEvents()
    w_prebuilt.hide()
    app.processEvents()

    painted_prebuilt = False
    paint_prebuilt_time = 0.0
    orig_prebuilt_paint = DonutWindow.paintEvent

    def on_prebuilt_paint(event):
        nonlocal painted_prebuilt, paint_prebuilt_time
        orig_prebuilt_paint(w_prebuilt, event)
        if not painted_prebuilt:
            painted_prebuilt = True
            paint_prebuilt_time = time.perf_counter()

    w_prebuilt.paintEvent = on_prebuilt_paint

    t_first_use_start = time.perf_counter()
    w_prebuilt.center_at(400, 400)
    w_prebuilt.capture_desktop_background()
    w_prebuilt.show()

    timeout = time.perf_counter() + 2.0
    while not painted_prebuilt and time.perf_counter() < timeout:
        app.processEvents()

    if not painted_prebuilt:
        paint_prebuilt_time = time.perf_counter()

    results["prebuilt_first_use_to_pixel_ms"] = (
        paint_prebuilt_time - t_first_use_start
    ) * 1000.0

    w_prebuilt.hide()
    app.processEvents()
    w_prebuilt.deleteLater()
    app.processEvents()

    # 3. Warm summon measurement (subsequent summons after initial use)
    w_warm = DonutWindow(files=[])
    w_warm.show()
    app.processEvents()
    w_warm.hide()
    app.processEvents()

    warm_times = []
    blur_times = []
    orig_warm_paint = DonutWindow.paintEvent

    for _ in range(5):
        painted_warm = False
        paint_warm_time = 0.0

        def make_paint_handler():
            def on_paint(event):
                nonlocal painted_warm, paint_warm_time
                orig_warm_paint(w_warm, event)
                if not painted_warm:
                    painted_warm = True
                    paint_warm_time = time.perf_counter()

            return on_paint

        w_warm.paintEvent = make_paint_handler()

        t_start = time.perf_counter()
        w_warm.reset_state()
        w_warm.center_at(500, 500)

        t_blur_start = time.perf_counter()
        w_warm.capture_desktop_background()
        blur_times.append((time.perf_counter() - t_blur_start) * 1000.0)

        w_warm.show()

        timeout = time.perf_counter() + 1.0
        while not painted_warm and time.perf_counter() < timeout:
            app.processEvents()

        if painted_warm:
            warm_times.append((paint_warm_time - t_start) * 1000.0)

        w_warm.hide()
        app.processEvents()

    avg_warm = sum(warm_times) / len(warm_times) if warm_times else 0.0
    results["warm_summon_to_pixel_avg_ms"] = avg_warm
    results["warm_summon_to_pixel_min_ms"] = min(warm_times) if warm_times else 0.0
    results["warm_summon_to_pixel_max_ms"] = max(warm_times) if warm_times else 0.0
    avg_blur = sum(blur_times) / len(blur_times) if blur_times else 0.0
    results["capture_blur_avg_ms"] = avg_blur

    w_warm.deleteLater()
    app.processEvents()

    return results


def main() -> None:
    print("=" * 60)
    print("smol Performance & Resource Benchmark")
    print("=" * 60)

    # 1. Daemon process status
    from smol.daemon.service import DaemonService

    svc = DaemonService()
    running, pid = svc.status()
    print(f"\n1. Daemon Status: {'Running' if running else 'Stopped'} (PID {pid})")

    if running and pid is not None:
        print(f"Sampling daemon PID {pid} idle CPU & memory over 5.0 seconds...")
        res = measure_daemon_resources(pid, sample_duration=5.0)
        print(f"  - Idle CPU Usage:   {res['cpu_percent']:.2f}% (Target: ~0%)")
        print(
            f"  - Resident Memory: {res['rss_mb']:.1f} MB "
            f"(Virtual: {res['vmsize_mb']:.1f} MB)"
        )
    else:
        print("  [Warning] Daemon not running. Start daemon to measure CPU/memory.")

    # 2. Donut UI Latency
    print("\n2. Measuring Donut Window Latency on active display...")
    latencies = measure_donut_latencies()
    print(f"  - DonutWindow.__init__ time:         {latencies['cold_init_ms']:.2f} ms")
    print(
        f"  - Cold Start (Un-cached First Pixel): "
        f"{latencies['cold_summon_to_first_pixel_ms']:.2f} ms"
    )
    print(
        f"  - Total Cold Start (Init + Pixel):    "
        f"{latencies['cold_total_time_ms']:.2f} ms"
    )
    print(
        f"  - Pre-built First-Use (First Pixel):  "
        f"{latencies['prebuilt_first_use_to_pixel_ms']:.2f} ms (Target < 150 ms)"
    )
    print(
        f"  - Background Grab & Blur (Average):   "
        f"{latencies['capture_blur_avg_ms']:.2f} ms"
    )
    print(
        f"  - Warm Summon to Visible (Average):   "
        f"{latencies['warm_summon_to_pixel_avg_ms']:.2f} ms (Target < 150 ms)"
    )
    print(
        f"  - Warm Summon to Visible (Min / Max): "
        f"{latencies['warm_summon_to_pixel_min_ms']:.2f} ms / "
        f"{latencies['warm_summon_to_pixel_max_ms']:.2f} ms"
    )

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
