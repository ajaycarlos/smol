"""Unit tests for daemon key/drag listener and summoning state machine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from smol.daemon.listener import (
    DragTracker,
    KeyHoldTracker,
    ListenerCoordinator,
    SummonMode,
    detect_session_type,
    ensure_ungrab,
    resolve_summon_mode,
)


def test_detect_session_type() -> None:
    assert detect_session_type({"XDG_SESSION_TYPE": "x11"}) == "x11"
    assert detect_session_type({"XDG_SESSION_TYPE": "wayland"}) == "wayland"
    assert detect_session_type({"WAYLAND_DISPLAY": "wayland-0"}) == "wayland"
    assert detect_session_type({"DISPLAY": ":0"}) == "x11"
    assert detect_session_type({}) == "unknown"


def test_resolve_summon_mode() -> None:
    # Explicit config overrides
    assert resolve_summon_mode("A", "wayland") == SummonMode.PATH_A
    assert resolve_summon_mode("C", "x11") == SummonMode.PATH_C

    # Auto resolution based on session
    assert resolve_summon_mode("auto", "x11") == SummonMode.PATH_A
    assert resolve_summon_mode("auto", "wayland") == SummonMode.PATH_C
    assert resolve_summon_mode(None, "x11") == SummonMode.PATH_A
    assert resolve_summon_mode(None, "wayland") == SummonMode.PATH_C


def test_key_hold_tracker() -> None:
    tracker = KeyHoldTracker(target_key="Super")

    # Press Super_L
    events = tracker.on_raw_key_down("Super_L", timestamp=100.0)
    assert events == ["PRESS Super"]
    assert tracker.is_target_pressed() is True

    # Repeated press should not duplicate
    events2 = tracker.on_raw_key_down("Super_L", timestamp=100.05)
    assert events2 == []

    # Release Super_L
    events3 = tracker.on_raw_key_up("Super_L", timestamp=100.25)
    assert len(events3) == 1
    assert "RELEASE Super held=250ms" in events3[0]
    assert tracker.is_target_pressed() is False


def test_key_hold_tracker_ctrl_alt() -> None:
    tracker = KeyHoldTracker(target_key="Ctrl+Alt")

    # Press Ctrl only -> not active
    assert tracker.on_raw_key_down("Control_L", timestamp=10.0) == []
    assert tracker.is_target_pressed() is False

    # Press Alt as well -> combo active
    events = tracker.on_raw_key_down("Alt_L", timestamp=10.1)
    assert events == ["PRESS Ctrl+Alt"]
    assert tracker.is_target_pressed() is True

    # Release Alt -> combo inactive
    events2 = tracker.on_raw_key_up("Alt_L", timestamp=10.3)
    assert len(events2) == 1
    assert "RELEASE Ctrl+Alt" in events2[0]
    assert tracker.is_target_pressed() is False


def test_drag_tracker_path_a() -> None:
    tracker = DragTracker(drag_threshold=6)

    # Mouse down without trigger key -> no drag start
    res0 = tracker.on_pointer_update(100, 100, button1_down=True, trigger_held=False)
    assert res0 is None
    assert tracker.is_dragging is False

    # Trigger key held, mouse not down -> no drag start
    tracker.on_pointer_update(100, 100, button1_down=False, trigger_held=True)
    assert tracker.is_dragging is False

    # Trigger key held + button1 down -> records origin
    res1 = tracker.on_pointer_update(100, 100, button1_down=True, trigger_held=True)
    assert res1 is None
    assert tracker.is_dragging is False

    # Moved 3px (< threshold 6px) -> no drag start yet
    res2 = tracker.on_pointer_update(103, 100, button1_down=True, trigger_held=True)
    assert res2 is None
    assert tracker.is_dragging is False

    # Moved 8px (>= threshold 6px) -> DRAG_START at current coords
    res3 = tracker.on_pointer_update(108, 100, button1_down=True, trigger_held=True)
    assert res3 == (108, 100)
    assert tracker.is_dragging is True

    # Further motion while still dragging does not re-emit DRAG_START
    res4 = tracker.on_pointer_update(120, 100, button1_down=True, trigger_held=True)
    assert res4 is None
    assert tracker.is_dragging is True

    # Button release resets drag
    tracker.on_pointer_update(120, 100, button1_down=False, trigger_held=True)
    assert tracker.is_dragging is False


def test_listener_coordinator_path_a() -> None:
    summon_mock = MagicMock()
    dismiss_mock = MagicMock()

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_summon=summon_mock,
        on_dismiss=dismiss_mock,
    )

    # 1. Trigger key pressed -> Path A does NOT summon yet
    coordinator.on_key_down("Super")
    summon_mock.assert_not_called()

    # 2. Drag starts at (500, 400) -> summons at cursor
    coordinator.on_drag_start(500, 400)
    summon_mock.assert_called_once_with(500, 400)
    assert coordinator.is_donut_visible is True

    # 3. Key released without drop -> dismisses donut
    coordinator.on_key_up("Super", held_ms=200.0)
    dismiss_mock.assert_called_once_with("key_release")
    assert coordinator.is_donut_visible is False


def test_listener_coordinator_path_c() -> None:
    summon_mock = MagicMock()
    dismiss_mock = MagicMock()

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_C,
        target_key="Super",
        on_summon=summon_mock,
        on_dismiss=dismiss_mock,
    )

    # 1. Trigger key pressed -> Path C immediately summons at
    # screen centre (None coords)
    coordinator.on_key_down("Super")
    summon_mock.assert_called_once_with(None, None)
    assert coordinator.is_donut_visible is True

    # 2. Key released without drop -> dismisses donut
    coordinator.on_key_up("Super", held_ms=300.0)
    dismiss_mock.assert_called_once_with("key_release")
    assert coordinator.is_donut_visible is False


def test_listener_coordinator_drop_preserves_donut() -> None:
    summon_mock = MagicMock()
    dismiss_mock = MagicMock()

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_summon=summon_mock,
        on_dismiss=dismiss_mock,
    )

    coordinator.on_key_down("Super")
    coordinator.on_drag_start(300, 300)
    assert coordinator.is_donut_visible is True

    # User drops file
    coordinator.on_drop_received(["/path/to/image.jpg"])
    assert coordinator.has_active_drop is True

    # Key released -> should NOT dismiss because drop was received!
    coordinator.on_key_up("Super", held_ms=500.0)
    dismiss_mock.assert_not_called()
    assert coordinator.is_donut_visible is True


def test_listener_coordinator_esc_dismisses_always() -> None:
    summon_mock = MagicMock()
    dismiss_mock = MagicMock()

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_summon=summon_mock,
        on_dismiss=dismiss_mock,
    )

    coordinator.on_key_down("Super")
    coordinator.on_drag_start(300, 300)
    assert coordinator.is_donut_visible is True

    # Esc pressed
    coordinator.on_esc_pressed()
    dismiss_mock.assert_called_once_with("esc")
    assert coordinator.is_donut_visible is False
    assert coordinator.has_active_drop is False


def test_ensure_ungrab_safe() -> None:
    # ensure_ungrab must never raise even if Xlib raises an exception or is absent
    with patch("Xlib.display.Display", side_effect=Exception("X connection failed")):
        ensure_ungrab()  # Must not raise


def test_key_hold_tracker_ctrl() -> None:
    """Verify plain Ctrl trigger key produces PRESS and RELEASE events."""
    tracker = KeyHoldTracker(target_key="Ctrl")

    events = tracker.on_raw_key_down("Control_L", timestamp=1.0)
    assert events == ["PRESS Ctrl"]
    assert tracker.is_target_pressed() is True

    events2 = tracker.on_raw_key_up("Control_L", timestamp=1.2)
    assert len(events2) == 1
    assert "RELEASE Ctrl" in events2[0]
    assert tracker.is_target_pressed() is False


def test_listener_coordinator_repeated_drags_after_completion() -> None:
    """Verify donut can be summoned repeatedly across multiple drag-and-drop jobs."""
    summon_mock = MagicMock()
    dismiss_mock = MagicMock()

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_summon=summon_mock,
        on_dismiss=dismiss_mock,
    )

    # First drag & drop
    coordinator.on_drag_start(100, 100)
    assert summon_mock.call_count == 1
    coordinator.on_drop_received(["file1.jpg"])
    assert coordinator.has_active_drop is True

    # Job finishes and window closes -> reset coordinator
    coordinator.reset()
    assert coordinator.has_active_drop is False
    assert coordinator.is_donut_visible is False

    # Second drag & drop
    coordinator.on_drag_start(200, 200)
    assert summon_mock.call_count == 2
    coordinator.on_drop_received(["file2.jpg"])

    coordinator.reset()

    # Third drag & drop
    coordinator.on_drag_start(300, 300)
    assert summon_mock.call_count == 3

