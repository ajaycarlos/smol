"""Spike A: Global key hold detection.

Detects globally (while another application has focus) when candidate trigger
keys are pressed and released:
  - Ctrl+Alt (both held)
  - Super
  - Right Alt
  - Right Ctrl

Prints:
  PRESS <key>
  RELEASE <key> held=<ms>ms
Followed by a PASS/FAIL summary for each candidate key.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Callable

CANDIDATE_KEYS = ["Ctrl+Alt", "Super", "Right Alt", "Right Ctrl"]

RAW_KEY_MAPPINGS = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "ISO_Level3_Shift": "alt",
    "Mode_switch": "alt",
    "Super_L": "super",
    "Super_R": "super",
}


def detect_session_type(env: dict[str, str] | None = None) -> str:
    """Detect current session type: 'x11', 'wayland', or 'unknown'."""
    if env is None:
        env = dict(os.environ)

    session_type = env.get("XDG_SESSION_TYPE", "").strip().lower()
    if session_type in ("x11", "wayland"):
        return session_type

    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"

    return "unknown"


def pick_backend(
    session_type: str,
    has_xlib: bool = True,
    has_evdev: bool = True,
) -> str:
    """Pick listener backend based on session type and available libraries."""
    if session_type == "x11":
        if has_xlib:
            return "xlib"
        if has_evdev:
            return "evdev"
        return "none"

    if session_type == "wayland":
        if has_evdev:
            return "evdev"
        return "portal_or_unavailable"

    if has_xlib:
        return "xlib"
    if has_evdev:
        return "evdev"
    return "none"


class KeyHoldTracker:
    """Tracks state and hold durations for candidate keys."""

    def __init__(self) -> None:
        self.pressed_at: dict[str, float] = {}
        self.raw_keys_down: set[str] = set()
        self.passed: set[str] = set()

    def on_press(
        self, candidate_key: str, timestamp: float | None = None
    ) -> str | None:
        """Record candidate key press. Returns formatted message or None if repeated."""
        if candidate_key in self.pressed_at:
            return None
        now = time.perf_counter() if timestamp is None else timestamp
        self.pressed_at[candidate_key] = now
        return f"PRESS {candidate_key}"

    def on_release(
        self, candidate_key: str, timestamp: float | None = None
    ) -> str | None:
        """Record candidate key release. Returns formatted message or None."""
        if candidate_key not in self.pressed_at:
            return None
        now = time.perf_counter() if timestamp is None else timestamp
        start = self.pressed_at.pop(candidate_key)
        held_ms = round((now - start) * 1000)
        self.passed.add(candidate_key)
        return f"RELEASE {candidate_key} held={held_ms}ms"

    def on_raw_key_down(
        self, raw_key: str, timestamp: float | None = None
    ) -> list[str]:
        """Update tracker with a raw key press event and return triggered messages."""
        if raw_key in self.raw_keys_down:
            return []
        self.raw_keys_down.add(raw_key)

        events: list[str] = []

        # Super candidate
        if raw_key in ("Super_L", "Super_R"):
            msg = self.on_press("Super", timestamp)
            if msg:
                events.append(msg)

        # Right Ctrl candidate
        if raw_key == "Control_R":
            msg = self.on_press("Right Ctrl", timestamp)
            if msg:
                events.append(msg)

        # Right Alt candidate
        if raw_key in ("Alt_R", "ISO_Level3_Shift", "Mode_switch"):
            msg = self.on_press("Right Alt", timestamp)
            if msg:
                events.append(msg)

        # Ctrl+Alt combo candidate (any Ctrl held and any Alt held)
        has_ctrl = any(k in self.raw_keys_down for k in ("Control_L", "Control_R"))
        has_alt = any(
            k in self.raw_keys_down
            for k in ("Alt_L", "Alt_R", "ISO_Level3_Shift", "Mode_switch")
        )
        if has_ctrl and has_alt and ("Ctrl+Alt" not in self.pressed_at):
            msg = self.on_press("Ctrl+Alt", timestamp)
            if msg:
                events.append(msg)

        return events

    def on_raw_key_up(self, raw_key: str, timestamp: float | None = None) -> list[str]:
        """Update tracker with a raw key release event and return triggered messages."""
        if raw_key not in self.raw_keys_down:
            return []
        self.raw_keys_down.discard(raw_key)

        events: list[str] = []

        # Super candidate
        if raw_key in ("Super_L", "Super_R") and not any(
            k in self.raw_keys_down for k in ("Super_L", "Super_R")
        ):
            msg = self.on_release("Super", timestamp)
            if msg:
                events.append(msg)

        # Right Ctrl candidate
        if raw_key == "Control_R":
            msg = self.on_release("Right Ctrl", timestamp)
            if msg:
                events.append(msg)

        # Right Alt candidate
        if raw_key in ("Alt_R", "ISO_Level3_Shift", "Mode_switch") and not any(
            k in self.raw_keys_down
            for k in ("Alt_R", "ISO_Level3_Shift", "Mode_switch")
        ):
            msg = self.on_release("Right Alt", timestamp)
            if msg:
                events.append(msg)

        # Ctrl+Alt combo candidate
        if "Ctrl+Alt" in self.pressed_at:
            has_ctrl = any(k in self.raw_keys_down for k in ("Control_L", "Control_R"))
            has_alt = any(
                k in self.raw_keys_down
                for k in ("Alt_L", "Alt_R", "ISO_Level3_Shift", "Mode_switch")
            )
            if not (has_ctrl and has_alt):
                msg = self.on_release("Ctrl+Alt", timestamp)
                if msg:
                    events.append(msg)

        return events

    def get_summary(self) -> dict[str, str]:
        """Return dict of candidate_key -> 'PASS' | 'FAIL'."""
        return {k: ("PASS" if k in self.passed else "FAIL") for k in CANDIDATE_KEYS}

    def all_passed(self) -> bool:
        """Return True if all candidate keys have passed."""
        return all(k in self.passed for k in CANDIDATE_KEYS)

    def format_summary(self) -> str:
        """Format the summary table."""
        summary = self.get_summary()
        lines = ["Candidate key results:"]
        for k in CANDIDATE_KEYS:
            lines.append(f"  {k}: {summary[k]}")
        return "\n".join(lines)


def run_x11_xrecord(
    tracker: KeyHoldTracker,
    on_event: Callable[[str], None] = print,
    stop_check: Callable[[], bool] | None = None,
) -> None:
    """Listen for global key events using X11 RECORD extension."""
    from Xlib import XK, X, display, error
    from Xlib.ext import record
    from Xlib.protocol import rq

    d_ctrl = display.Display()
    d_data = display.Display()

    # Build keycode to raw key name mapping
    keycode_map: dict[int, str] = {}
    target_names = [
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Super_L",
        "Super_R",
        "ISO_Level3_Shift",
        "Mode_switch",
    ]
    for name in target_names:
        keysym = getattr(XK, "XK_" + name, None)
        if keysym:
            code = d_ctrl.keysym_to_keycode(keysym)
            if code:
                keycode_map[code] = name

    # Standard default PC keycodes if keysym lookup didn't cover
    standard_defaults = {
        37: "Control_L",
        105: "Control_R",
        64: "Alt_L",
        108: "Alt_R",
        133: "Super_L",
        134: "Super_R",
    }
    for code, name in standard_defaults.items():
        if code not in keycode_map:
            keycode_map[code] = name

    ctx = d_ctrl.record_create_context(
        0,
        [record.AllClients],
        [
            {
                "core_requests": (0, 0),
                "core_replies": (0, 0),
                "ext_requests": (0, 0, 0, 0),
                "ext_replies": (0, 0, 0, 0),
                "delivered_events": (0, 0),
                "device_events": (X.KeyPress, X.KeyRelease),
                "errors": (0, 0),
                "client_started": False,
                "client_died": False,
            }
        ],
    )

    def process_reply(reply: rq.ReplyRequest) -> None:
        if reply.category != record.FromServer or reply.client_swapped:
            return
        if not len(reply.data) or reply.data[0] < 2:
            return

        data = reply.data
        while len(data):
            event, data = rq.EventField(None).parse_binary_value(
                data, d_data.display, None, None
            )
            raw_key = keycode_map.get(event.detail)
            if not raw_key:
                continue

            msgs: list[str] = []
            if event.type == X.KeyPress:
                msgs = tracker.on_raw_key_down(raw_key)
            elif event.type == X.KeyRelease:
                msgs = tracker.on_raw_key_up(raw_key)

            for msg in msgs:
                on_event(msg)

            if tracker.all_passed() or (stop_check and stop_check()):
                d_ctrl.record_disable_context(ctx)
                d_ctrl.flush()
                return

    try:
        d_data.record_enable_context(ctx, process_reply)
    except error.XError:
        pass
    finally:
        with contextlib.suppress(Exception):
            d_ctrl.record_disable_context(ctx)
            d_ctrl.flush()
            d_ctrl.record_free_context(ctx)


def run_x11_query_keymap(
    tracker: KeyHoldTracker,
    on_event: Callable[[str], None] = print,
    poll_interval: float = 0.01,
    stop_check: Callable[[], bool] | None = None,
) -> None:
    """Listen for global key state changes using X11 query_keymap polling."""
    from Xlib import XK, display

    d = display.Display()

    keycode_map: dict[int, str] = {}
    target_names = [
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Super_L",
        "Super_R",
        "ISO_Level3_Shift",
        "Mode_switch",
    ]
    for name in target_names:
        keysym = getattr(XK, "XK_" + name, None)
        if keysym:
            code = d.keysym_to_keycode(keysym)
            if code:
                keycode_map[code] = name

    standard_defaults = {
        37: "Control_L",
        105: "Control_R",
        64: "Alt_L",
        108: "Alt_R",
        133: "Super_L",
        134: "Super_R",
    }
    for code, name in standard_defaults.items():
        if code not in keycode_map:
            keycode_map[code] = name

    last_state: dict[int, bool] = {kc: False for kc in keycode_map}

    while True:
        km = d.query_keymap()
        now = time.perf_counter()

        for kc, raw_name in keycode_map.items():
            is_down = bool((km[kc // 8] >> (kc % 8)) & 1)
            was_down = last_state[kc]

            if is_down and not was_down:
                last_state[kc] = True
                for msg in tracker.on_raw_key_down(raw_name, timestamp=now):
                    on_event(msg)
            elif not is_down and was_down:
                last_state[kc] = False
                for msg in tracker.on_raw_key_up(raw_name, timestamp=now):
                    on_event(msg)

        if tracker.all_passed() or (stop_check and stop_check()):
            break

        time.sleep(poll_interval)


def run_evdev_listener(
    tracker: KeyHoldTracker,
    on_event: Callable[[str], None] = print,
    stop_check: Callable[[], bool] | None = None,
) -> None:
    """Listen for global key events using Linux evdev (/dev/input)."""
    import select

    import evdev
    from evdev import ecodes

    device_paths = evdev.list_devices()
    if not device_paths:
        raise PermissionError(
            "No accessible /dev/input devices found. Ensure your user belongs to "
            "the 'input' group (run: sudo usermod -a -G input $USER) or run with sudo."
        )

    # Filter devices that have EV_KEY capabilities
    keyboards: list[evdev.InputDevice] = []
    for path in device_paths:
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                keyboards.append(dev)
        except (PermissionError, OSError):
            continue

    if not keyboards:
        raise PermissionError(
            "Cannot open keyboard devices under /dev/input. "
            "Ensure you have read permissions (e.g. member of 'input' group)."
        )

    evdev_map = {
        ecodes.KEY_LEFTCTRL: "Control_L",
        ecodes.KEY_RIGHTCTRL: "Control_R",
        ecodes.KEY_LEFTALT: "Alt_L",
        ecodes.KEY_RIGHTALT: "Alt_R",
        ecodes.KEY_LEFTMETA: "Super_L",
        ecodes.KEY_RIGHTMETA: "Super_R",
    }

    fd_to_dev = {dev.fd: dev for dev in keyboards}

    while True:
        r, _, _ = select.select(list(fd_to_dev.keys()), [], [], 0.05)
        now = time.perf_counter()
        for fd in r:
            dev = fd_to_dev[fd]
            try:
                for event in dev.read():
                    if event.type != ecodes.EV_KEY:
                        continue
                    raw_key = evdev_map.get(event.code)
                    if not raw_key:
                        continue

                    # value 1 = press, 0 = release (2 = repeat)
                    msgs: list[str] = []
                    if event.value == 1:
                        msgs = tracker.on_raw_key_down(raw_key, timestamp=now)
                    elif event.value == 0:
                        msgs = tracker.on_raw_key_up(raw_key, timestamp=now)

                    for msg in msgs:
                        on_event(msg)
            except OSError:
                pass

        if tracker.all_passed() or (stop_check and stop_check()):
            break


def main() -> int:
    """Main CLI entry point for Spike A."""
    print("=" * 60)
    print("  smol Spike A: Global Key Hold Detection")
    print("=" * 60)

    session_type = detect_session_type()
    print(f"Session type detected: {session_type}")

    has_xlib = False
    try:
        import Xlib  # noqa: F401

        has_xlib = True
    except ImportError:
        pass

    has_evdev = False
    try:
        import evdev  # noqa: F401

        has_evdev = True
    except ImportError:
        pass

    backend = pick_backend(session_type, has_xlib=has_xlib, has_evdev=has_evdev)
    print(f"Libraries available: python-xlib={has_xlib}, evdev={has_evdev}")
    print(f"Selected backend:    {backend}")
    print("-" * 60)

    if backend == "none":
        print("ERROR: No suitable backend available for this session.")
        if session_type == "x11":
            print("To run on X11, install python-xlib (no extra permissions needed):")
            print("  uv run --with python-xlib python spikes/a_key_hold.py")
            print("Or install evdev (requires member of 'input' group):")
            print("  uv run --with evdev python spikes/a_key_hold.py")
        return 1

    if backend == "portal_or_unavailable":
        print("Wayland detected. evdev requires access to /dev/input/event*.")
        print("Please ensure your user is in the 'input' group:")
        print("  sudo usermod -a -G input $USER")
        print("Then log out and log back in, or run:")
        print("  uv run --with evdev python spikes/a_key_hold.py")
        return 1

    print("Candidate trigger keys to test:")
    for k in CANDIDATE_KEYS:
        print(f"  [ ] {k}")
    print("\nInstructions:")
    print("  Focus another window (e.g. text editor or browser) or test right here.")
    print("  Hold and release each candidate key. Press Ctrl+C when done.\n")

    tracker = KeyHoldTracker()

    try:
        if backend == "xlib":
            if "--use-record" in sys.argv:
                try:
                    run_x11_xrecord(tracker, on_event=print)
                except (OSError, RuntimeError) as e:
                    print(f"(XRecord failed: {e}; falling back to query_keymap)")
                    run_x11_query_keymap(tracker, on_event=print)
            else:
                run_x11_query_keymap(tracker, on_event=print)
        elif backend == "evdev":
            run_evdev_listener(tracker, on_event=print)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except (OSError, RuntimeError) as e:
        print(f"\nExecution error: {e}")

    print("\n" + "=" * 60)
    print(tracker.format_summary())
    print("=" * 60)

    return 0 if tracker.all_passed() else 1


if __name__ == "__main__":
    sys.exit(main())
