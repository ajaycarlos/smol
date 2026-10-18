"""Spike B: Mouse drag and global cursor position detection.

While a candidate trigger key from Spike A is held:
  - Ctrl+Alt
  - Super
  - Right Alt
  - Right Ctrl

Detect when the user starts dragging a file in their file manager (e.g. Nemo),
read the global cursor position in screen coordinates, and print:
  DRAG_START x=<n> y=<n>
Followed by PASS/FAIL.

If global cursor query is restricted on the current session type (e.g. GNOME Wayland),
state so plainly with architectural evidence and provide the screen centre fallback.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable
from typing import Any

try:
    from spikes.a_key_hold import (
        CANDIDATE_KEYS,
        KeyHoldTracker,
        detect_session_type,
    )
except ImportError:
    from a_key_hold import (  # type: ignore[no-redef]
        CANDIDATE_KEYS,
        KeyHoldTracker,
        detect_session_type,
    )


def get_cursor_support(session_type: str) -> tuple[bool, str]:
    """Check if global cursor reading is supported on the session type.

    Returns (is_supported, explanation_or_evidence).
    """
    st = session_type.strip().lower()
    if st == "x11":
        return (
            True,
            "Supported (X11 XQueryPointer queries root window coordinates globally).",
        )
    if st == "wayland":
        msg = (
            "Unsupported on Wayland: Security architecture isolates pointer and input "
            "events between client surfaces. Core Wayland protocol deliberately "
            "prevents unprivileged applications from querying global cursor "
            "coordinates outside their own windows."
        )
        return (False, msg)
    return (
        False,
        f"Unsupported: Session type '{session_type}' lacks global cursor access.",
    )


def get_screen_centre(width: int, height: int) -> tuple[int, int]:
    """Return the centre coordinates of a screen with the given dimensions."""
    return (width // 2, height // 2)


def get_cursor_fallback(
    width: int = 1920, height: int = 1080, session_type: str = "wayland"
) -> tuple[tuple[int, int], str]:
    """Provide the screen centre fallback coordinates and explanatory rationale."""
    centre = get_screen_centre(width, height)
    message = (
        f"Fallback: Screen centre ({centre[0]}, {centre[1]}) used because "
        f"global cursor query is restricted on {session_type}."
    )
    return centre, message


class DragTracker:
    """Tracks mouse button, cursor motion, and trigger keys to detect drag start."""

    def __init__(
        self,
        drag_threshold: int = 6,
        candidate_keys: list[str] | None = None,
    ) -> None:
        self.drag_threshold = drag_threshold
        self.candidate_keys = (
            list(candidate_keys) if candidate_keys else list(CANDIDATE_KEYS)
        )
        self.active_keys: set[str] = set()
        self.button1_down: bool = False
        self.drag_origin: tuple[int, int] | None = None
        self.is_dragging: bool = False
        self.drag_count: int = 0
        self.last_drag_coords: tuple[int, int] | None = None
        self.last_trigger_key: str | None = None

    def on_key_press(self, key: str) -> None:
        """Record candidate trigger key press."""
        self.active_keys.add(key)
        self.last_trigger_key = key

    def on_key_release(self, key: str) -> None:
        """Record candidate trigger key release."""
        self.active_keys.discard(key)
        if not self.active_keys:
            self.is_dragging = False
            self.drag_origin = None

    def on_pointer_update(
        self, x: int, y: int, button1_down: bool
    ) -> str | None:
        """Update pointer coordinates and button1 state.

        Returns 'DRAG_START x=<n> y=<n>' if a new drag is initiated while a
        trigger key is held, else None.
        """
        self.button1_down = button1_down

        if not button1_down or not self.active_keys:
            self.is_dragging = False
            self.drag_origin = None
            return None

        # Both button1 is down and at least one trigger key is held
        if self.drag_origin is None:
            self.drag_origin = (x, y)
            return None

        origin_x, origin_y = self.drag_origin
        distance = math.hypot(x - origin_x, y - origin_y)

        if distance >= self.drag_threshold and not self.is_dragging:
            self.is_dragging = True
            self.drag_count += 1
            self.last_drag_coords = (x, y)
            return f"DRAG_START x={x} y={y}"

        return None

    def has_drag_detected(self) -> bool:
        """Return True if at least one drag start was detected."""
        return self.drag_count > 0

    def get_summary(self) -> dict[str, Any]:
        """Return summary dictionary."""
        return {
            "status": "PASS" if self.has_drag_detected() else "FAIL",
            "drag_count": self.drag_count,
            "last_drag": self.last_drag_coords,
            "last_trigger_key": self.last_trigger_key,
        }

    def format_summary(self) -> str:
        """Format the summary table."""
        summary = self.get_summary()
        status = summary["status"]
        count = summary["drag_count"]
        last = summary["last_drag"]
        trigger = summary["last_trigger_key"] or "none"
        coords_str = f"x={last[0]} y={last[1]}" if last else "none"

        lines = [
            "=" * 60,
            "smol Spike B Results:",
            f"  Status:               {status}",
            f"  Drags detected:       {count}",
            f"  Last trigger key:     {trigger}",
            f"  Last coordinates:     {coords_str}",
            "=" * 60,
        ]
        return "\n".join(lines)


def run_x11_drag_listener(
    drag_tracker: DragTracker,
    key_tracker: KeyHoldTracker | None = None,
    on_event: Callable[[str], None] = print,
    once: bool = False,
    poll_interval: float = 0.015,
    stop_check: Callable[[], bool] | None = None,
) -> None:
    """Listen for trigger key hold and pointer drag events on X11."""
    try:
        from Xlib import XK, X, display
    except ImportError as e:
        raise ImportError(
            "python-xlib is required for X11 drag and cursor tracking. "
            "Run with: uv run --with python-xlib python spikes/b_drag_and_cursor.py"
        ) from e

    d = display.Display()
    screen = d.screen()
    root = screen.root

    if key_tracker is None:
        key_tracker = KeyHoldTracker()

    # Map keycodes to raw keys
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
    keycode_map: dict[int, str] = {}
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

    last_key_state: dict[int, bool] = {kc: False for kc in keycode_map}

    while True:
        now = time.perf_counter()

        # 1. Update key states
        km = d.query_keymap()
        for kc, raw_name in keycode_map.items():
            is_down = bool((km[kc // 8] >> (kc % 8)) & 1)
            was_down = last_key_state[kc]

            if is_down and not was_down:
                last_key_state[kc] = True
                for msg in key_tracker.on_raw_key_down(raw_name, timestamp=now):
                    if msg.startswith("PRESS "):
                        trigger = msg[len("PRESS ") :]
                        drag_tracker.on_key_press(trigger)
            elif not is_down and was_down:
                last_key_state[kc] = False
                for msg in key_tracker.on_raw_key_up(raw_name, timestamp=now):
                    if msg.startswith("RELEASE "):
                        trigger = msg.split()[1]
                        drag_tracker.on_key_release(trigger)

        # 2. Update pointer state
        pointer = root.query_pointer()
        root_x = pointer.root_x
        root_y = pointer.root_y
        button1_down = bool(pointer.mask & X.Button1Mask)

        drag_msg = drag_tracker.on_pointer_update(root_x, root_y, button1_down)
        if drag_msg:
            on_event(drag_msg)
            trig = drag_tracker.last_trigger_key
            on_event(f"PASS (trigger={trig}, x={root_x}, y={root_y})")
            if once:
                break

        if stop_check and stop_check():
            break

        time.sleep(poll_interval)


def main() -> int:
    """CLI entry point for Spike B."""
    parser = argparse.ArgumentParser(
        description="smol Spike B: Mouse drag and global cursor position detection."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit immediately after first drag detection.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=6,
        help="Drag distance threshold in pixels (default: 6).",
    )
    args = parser.parse_args()

    session_type = detect_session_type()
    supported, support_reason = get_cursor_support(session_type)

    print("=" * 60)
    print("  smol Spike B: Drag and Cursor Detection")
    print("=" * 60)
    print(f"Session type detected: {session_type}")
    print(f"Global cursor query:   {'SUPPORTED' if supported else 'UNSUPPORTED'}")
    print(f"Reason:                {support_reason}")
    print("-" * 60)

    if not supported:
        fallback_coords, fallback_reason = get_cursor_fallback(
            session_type=session_type
        )
        print(f"Evidence: {support_reason}")
        print(f"{fallback_reason}")
        print(f"DRAG_START x={fallback_coords[0]} y={fallback_coords[1]} (FALLBACK)")
        print("FAIL (global cursor unavailable on this session type)")
        print("=" * 60)
        return 1

    print("Candidate trigger keys:")
    for k in CANDIDATE_KEYS:
        print(f"  [ ] {k}")
    print()
    print("Instructions:")
    print("  1. Focus your file manager (e.g. Nemo).")
    print("  2. Hold candidate trigger key (Ctrl+Alt, Super, Right Alt, Right Ctrl).")
    print("  3. Click and drag a file with the left mouse button.")
    print("  4. Notice the DRAG_START x=<n> y=<n> output.")
    print("  5. Press Ctrl+C when done.")
    print("-" * 60)

    drag_tracker = DragTracker(drag_threshold=args.threshold)
    key_tracker = KeyHoldTracker()

    try:
        run_x11_drag_listener(
            drag_tracker=drag_tracker,
            key_tracker=key_tracker,
            once=args.once,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user.\n")
    except (OSError, RuntimeError, ImportError) as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1

    print(drag_tracker.format_summary())
    return 0 if drag_tracker.has_drag_detected() else 1


if __name__ == "__main__":
    sys.exit(main())
