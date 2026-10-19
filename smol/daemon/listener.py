"""Low-level event listener and state coordinator for smol daemon.

Tracks global modifier key hold state (Super / Ctrl+Alt), pointer drag detection,
and coordinates overlay summoning between Path A (cursor overlay on X11) and
Path C (screen-centre drop palette on Wayland/fallback).

Guarantees safety: never leaves the keyboard or mouse grabbed if something crashes.
"""

from __future__ import annotations

import atexit
import contextlib
import enum
import math
import os
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

CANDIDATE_KEYS = ["Super", "Ctrl+Alt", "Right Alt", "Right Ctrl"]

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


class SummonMode(enum.Enum):
    PATH_A = "Path A (cursor overlay on drag)"
    PATH_C = "Path C (screen-centre palette on key hold)"


def ensure_ungrab() -> None:
    """Unconditionally release any X11 keyboard or pointer grabs.

    Safe to call repeatedly; swallows all exceptions.
    """
    with contextlib.suppress(Exception):
        from Xlib import X, display

        d = display.Display()
        try:
            d.ungrab_keyboard(X.CurrentTime)
            d.ungrab_pointer(X.CurrentTime)
            d.flush()
        finally:
            d.close()



# Register ungrab on process exit
atexit.register(ensure_ungrab)


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


def resolve_summon_mode(
    config_mode: str | None = None,
    session_type: str | None = None,
) -> SummonMode:
    """Resolve whether to use Path A or Path C.

    - Path A: when trigger key is held and a drag begins, show donut at cursor position.
    - Path C: when trigger key is held, show donut at screen centre.
    """
    if config_mode is not None:
        cm = config_mode.strip().upper()
        if cm == "A":
            return SummonMode.PATH_A
        if cm == "C":
            return SummonMode.PATH_C

    if session_type is None:
        session_type = detect_session_type()

    if session_type == "x11":
        return SummonMode.PATH_A

    return SummonMode.PATH_C


class KeyHoldTracker:
    """Tracks state and hold durations for trigger keys."""

    def __init__(self, target_key: str = "Super") -> None:
        self.target_key = target_key
        self.pressed_at: dict[str, float] = {}
        self.raw_keys_down: set[str] = set()

    def is_target_pressed(self) -> bool:
        """Return True if the target trigger key/combination is currently held."""
        if self.target_key == "Super":
            return any(k in self.raw_keys_down for k in ("Super_L", "Super_R"))
        if self.target_key == "Ctrl+Alt":
            has_ctrl = any(k in self.raw_keys_down for k in ("Control_L", "Control_R"))
            has_alt = any(
                k in self.raw_keys_down
                for k in ("Alt_L", "Alt_R", "ISO_Level3_Shift", "Mode_switch")
            )
            return has_ctrl and has_alt
        if self.target_key == "Right Alt":
            return any(
                k in self.raw_keys_down
                for k in ("Alt_R", "ISO_Level3_Shift", "Mode_switch")
            )
        if self.target_key == "Right Ctrl":
            return "Control_R" in self.raw_keys_down

        return self.target_key in self.pressed_at

    def on_raw_key_down(
        self, raw_key: str, timestamp: float | None = None
    ) -> list[str]:
        """Update tracker with a raw key press event and return triggered events."""
        now = time.perf_counter() if timestamp is None else timestamp
        if raw_key in self.raw_keys_down:
            return []

        self.raw_keys_down.add(raw_key)
        events: list[str] = []

        # Super candidate
        if raw_key in ("Super_L", "Super_R") and "Super" not in self.pressed_at:
            self.pressed_at["Super"] = now
            if self.target_key == "Super":
                events.append("PRESS Super")

        # Right Ctrl candidate
        if raw_key == "Control_R" and "Right Ctrl" not in self.pressed_at:
            self.pressed_at["Right Ctrl"] = now
            if self.target_key == "Right Ctrl":
                events.append("PRESS Right Ctrl")

        # Right Alt candidate
        if (
            raw_key in ("Alt_R", "ISO_Level3_Shift", "Mode_switch")
            and "Right Alt" not in self.pressed_at
        ):
            self.pressed_at["Right Alt"] = now
            if self.target_key == "Right Alt":
                events.append("PRESS Right Alt")

        # Ctrl+Alt combo candidate
        has_ctrl = any(k in self.raw_keys_down for k in ("Control_L", "Control_R"))
        has_alt = any(
            k in self.raw_keys_down
            for k in ("Alt_L", "Alt_R", "ISO_Level3_Shift", "Mode_switch")
        )
        if has_ctrl and has_alt and "Ctrl+Alt" not in self.pressed_at:
            self.pressed_at["Ctrl+Alt"] = now
            if self.target_key == "Ctrl+Alt":
                events.append("PRESS Ctrl+Alt")

        return events

    def on_raw_key_up(
        self, raw_key: str, timestamp: float | None = None
    ) -> list[str]:
        """Update tracker with a raw key release event and return triggered events."""
        now = time.perf_counter() if timestamp is None else timestamp
        if raw_key not in self.raw_keys_down:
            return []

        self.raw_keys_down.discard(raw_key)
        events: list[str] = []

        # Super candidate
        if raw_key in ("Super_L", "Super_R") and not any(
            k in self.raw_keys_down for k in ("Super_L", "Super_R")
        ):
            press_t = self.pressed_at.pop("Super", None)
            if press_t is not None and self.target_key == "Super":
                held_ms = int((now - press_t) * 1000.0)
                events.append(f"RELEASE Super held={held_ms}ms")

        # Right Ctrl candidate
        if raw_key == "Control_R":
            press_t = self.pressed_at.pop("Right Ctrl", None)
            if press_t is not None and self.target_key == "Right Ctrl":
                held_ms = int((now - press_t) * 1000.0)
                events.append(f"RELEASE Right Ctrl held={held_ms}ms")

        # Right Alt candidate
        if raw_key in ("Alt_R", "ISO_Level3_Shift", "Mode_switch") and not any(
            k in self.raw_keys_down
            for k in ("Alt_R", "ISO_Level3_Shift", "Mode_switch")
        ):
            press_t = self.pressed_at.pop("Right Alt", None)
            if press_t is not None and self.target_key == "Right Alt":
                held_ms = int((now - press_t) * 1000.0)
                events.append(f"RELEASE Right Alt held={held_ms}ms")

        # Ctrl+Alt combo candidate
        if "Ctrl+Alt" in self.pressed_at:
            has_ctrl = any(k in self.raw_keys_down for k in ("Control_L", "Control_R"))
            has_alt = any(
                k in self.raw_keys_down
                for k in ("Alt_L", "Alt_R", "ISO_Level3_Shift", "Mode_switch")
            )
            if not (has_ctrl and has_alt):
                press_t = self.pressed_at.pop("Ctrl+Alt", None)
                if press_t is not None and self.target_key == "Ctrl+Alt":
                    held_ms = int((now - press_t) * 1000.0)
                    events.append(f"RELEASE Ctrl+Alt held={held_ms}ms")

        return events


class DragTracker:
    """Tracks mouse button and pointer motion to detect file drag initiation."""

    def __init__(self, drag_threshold: int = 6) -> None:
        self.drag_threshold = drag_threshold
        self.drag_origin: tuple[int, int] | None = None
        self.is_dragging: bool = False

    def on_pointer_update(
        self, x: int, y: int, button1_down: bool, trigger_held: bool
    ) -> tuple[int, int] | None:
        """Update pointer coordinates and button state.

        Returns (x, y) if a new drag is initiated while trigger is held, else None.
        """
        if not button1_down or not trigger_held:
            self.is_dragging = False
            self.drag_origin = None
            return None

        if self.drag_origin is None:
            self.drag_origin = (x, y)
            return None

        origin_x, origin_y = self.drag_origin
        distance = math.hypot(x - origin_x, y - origin_y)

        if distance >= self.drag_threshold and not self.is_dragging:
            self.is_dragging = True
            return (x, y)

        return None

    def reset(self) -> None:
        """Reset drag state."""
        self.drag_origin = None
        self.is_dragging = False


class ListenerCoordinator:
    """Coordinates key and drag events with DonutWindow summoning lifecycle.

    - Path A: when trigger key is held and drag begins -> summon at (x, y).
    - Path C: when trigger key is pressed -> summon at screen centre (None coords).
    - When trigger key is released without drop -> dismiss donut.
    - When Esc is pressed -> dismiss donut.
    - If a drop was received and job is active -> preserve donut to show result.
    """

    def __init__(
        self,
        mode: SummonMode = SummonMode.PATH_A,
        target_key: str = "Super",
        on_summon: Callable[[int | None, int | None], None] | None = None,
        on_dismiss: Callable[[str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.mode = mode
        self.target_key = target_key
        self.on_summon = on_summon
        self.on_dismiss = on_dismiss
        self.on_log = on_log

        self.key_tracker = KeyHoldTracker(target_key=target_key)
        self.drag_tracker = DragTracker()

        self.is_donut_visible: bool = False
        self.has_active_drop: bool = False

    def log(self, message: str) -> None:
        if self.on_log is not None:
            self.on_log(message)

    def on_key_down(self, key_name: str) -> None:
        """Handle candidate trigger key press event."""
        self.log(f"Trigger key '{key_name}' pressed.")
        if self.mode == SummonMode.PATH_C and not self.is_donut_visible:
            self.is_donut_visible = True
            self.has_active_drop = False
            self.log(f"Summoning donut at screen centre ({self.mode.value}).")
            if self.on_summon is not None:
                self.on_summon(None, None)

    def on_key_up(self, key_name: str, held_ms: float = 0.0) -> None:
        """Handle candidate trigger key release event."""
        self.log(f"Trigger key '{key_name}' released after {int(held_ms)}ms.")
        self.drag_tracker.reset()
        if self.is_donut_visible and not self.has_active_drop:
            self.log("Trigger key released without drop; hiding donut overlay.")
            self.is_donut_visible = False
            if self.on_dismiss is not None:
                self.on_dismiss("key_release")

    def on_drag_start(self, x: int, y: int) -> None:
        """Handle drag start at global coordinates (x, y)."""
        self.log(
            f"Drag started at x={x}, y={y} while trigger key '{self.target_key}' held."
        )
        if not self.is_donut_visible:
            self.is_donut_visible = True
            self.has_active_drop = False
            self.log(f"Summoning donut at cursor x={x}, y={y} ({self.mode.value}).")
            if self.on_summon is not None:
                self.on_summon(x, y)

    def on_drag_cancelled(self) -> None:
        """Handle drag cancellation midway."""
        self.drag_tracker.reset()
        if self.is_donut_visible and not self.has_active_drop:
            self.log("Drag cancelled midway; hiding donut overlay.")
            self.is_donut_visible = False
            if self.on_dismiss is not None:
                self.on_dismiss("drag_cancelled")

    def on_drop_received(self, files: list[Any]) -> None:
        """Mark that a file drop was received on the donut."""
        self.has_active_drop = True
        self.log(f"Drop received: {len(files)} files ({files}).")

    def on_esc_pressed(self) -> None:
        """Handle Esc key cancellation."""
        self.drag_tracker.reset()
        if self.is_donut_visible:
            self.log("Donut dismissed via Esc key.")
            self.is_donut_visible = False
            self.has_active_drop = False
            if self.on_dismiss is not None:
                self.on_dismiss("esc")

    def on_click_outside(self) -> None:
        """Handle click outside donut."""
        self.drag_tracker.reset()
        if self.is_donut_visible:
            self.log("Donut dismissed via click outside.")
            self.is_donut_visible = False
            self.has_active_drop = False
            if self.on_dismiss is not None:
                self.on_dismiss("outside")

    def reset(self) -> None:
        """Reset coordinator state."""
        self.is_donut_visible = False
        self.has_active_drop = False
        self.drag_tracker.reset()


class X11EventListener(QThread):
    """Background polling thread that monitors X11 keys and pointer state."""

    key_down = Signal(str)
    key_up = Signal(str, float)
    drag_started = Signal(int, int)
    drag_cancelled = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        target_key: str = "Super",
        poll_interval: float = 0.015,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.target_key = target_key
        self.poll_interval = poll_interval
        self._stop_requested = False
        self.key_tracker = KeyHoldTracker(target_key=target_key)
        self.drag_tracker = DragTracker()

    def stop(self) -> None:
        """Signal thread to stop and wait for completion."""
        self._stop_requested = True
        self.wait(1000)

    def run(self) -> None:
        """Main listener loop querying keymap and pointer state."""
        try:
            from Xlib import XK, X, display
        except ImportError as e:
            self.error_occurred.emit(f"python-xlib not available: {e}")
            return

        try:
            d = display.Display()
        except Exception as e:  # noqa: BLE001
            self.error_occurred.emit(f"Cannot connect to X display: {e}")
            return

        try:
            screen = d.screen()
            root = screen.root

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

            while not self._stop_requested:
                now = time.perf_counter()

                # Query key states
                km = d.query_keymap()
                for kc, raw_name in keycode_map.items():
                    is_down = bool((km[kc // 8] >> (kc % 8)) & 1)
                    was_down = last_key_state.get(kc, False)

                    if is_down and not was_down:
                        last_key_state[kc] = True
                        for msg in self.key_tracker.on_raw_key_down(
                            raw_name, timestamp=now
                        ):
                            if msg.startswith("PRESS "):
                                key_pressed = msg[len("PRESS ") :]
                                self.key_down.emit(key_pressed)
                    elif not is_down and was_down:
                        last_key_state[kc] = False
                        for msg in self.key_tracker.on_raw_key_up(
                            raw_name, timestamp=now
                        ):
                            if msg.startswith("RELEASE "):
                                parts = msg.split()
                                key_released = parts[1]
                                held_ms = 0.0
                                for p in parts[2:]:
                                    if p.startswith("held="):
                                        held_ms = float(p[len("held=") :].rstrip("ms"))
                                self.key_up.emit(key_released, held_ms)

                trigger_held = self.key_tracker.is_target_pressed()
                if trigger_held:
                    pointer = root.query_pointer()
                    root_x = pointer.root_x
                    root_y = pointer.root_y
                    button1_down = bool(pointer.mask & X.Button1Mask)
                    was_dragging = self.drag_tracker.is_dragging
                    drag_coords = self.drag_tracker.on_pointer_update(
                        root_x, root_y, button1_down, trigger_held
                    )
                    if drag_coords is not None:
                        self.drag_started.emit(drag_coords[0], drag_coords[1])
                    elif was_dragging and not button1_down:
                        self.drag_tracker.reset()
                        self.drag_cancelled.emit()
                    time.sleep(self.poll_interval)
                else:
                    time.sleep(0.025)
        except Exception as e:  # noqa: BLE001
            self.error_occurred.emit(f"X11 listener exception: {e}")
        finally:
            ensure_ungrab()
            with contextlib.suppress(Exception):
                d.close()

