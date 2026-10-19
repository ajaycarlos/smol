from spikes.b_drag_and_cursor import (
    DragTracker,
    get_cursor_fallback,
    get_cursor_support,
    get_screen_centre,
)


def test_detect_session_type_and_cursor_support():
    supported_x11, reason_x11 = get_cursor_support("x11")
    assert supported_x11 is True
    assert "x11" in reason_x11.lower() or "xquerypointer" in reason_x11.lower()

    supported_wl, reason_wl = get_cursor_support("wayland")
    assert supported_wl is False
    assert "wayland" in reason_wl.lower() or "security" in reason_wl.lower()

    supported_unk, reason_unk = get_cursor_support("unknown")
    assert supported_unk is False
    assert "unknown" in reason_unk.lower()


def test_get_screen_centre():
    assert get_screen_centre(1920, 1080) == (960, 540)
    assert get_screen_centre(2560, 1440) == (1280, 720)
    assert get_screen_centre(0, 0) == (0, 0)


def test_cursor_fallback_info():
    coords, msg = get_cursor_fallback(width=1920, height=1080, session_type="wayland")
    assert coords == (960, 540)
    assert "fallback" in msg.lower()
    assert "wayland" in msg.lower()


def test_drag_tracker_requires_key_held():
    tracker = DragTracker(drag_threshold=5, candidate_keys=["Super", "Ctrl+Alt"])

    # Button 1 pressed at (100, 100)
    msg = tracker.on_pointer_update(100, 100, button1_down=True)
    assert msg is None

    # Moved to (150, 150) without trigger key held -> no drag
    msg = tracker.on_pointer_update(150, 150, button1_down=True)
    assert msg is None
    assert not tracker.has_drag_detected()
    assert tracker.get_summary()["status"] == "FAIL"


def test_drag_tracker_detects_drag_when_key_held():
    tracker = DragTracker(drag_threshold=5, candidate_keys=["Super", "Ctrl+Alt"])

    # Key is pressed
    tracker.on_key_press("Super")

    # Mouse button pressed at (200, 300)
    msg1 = tracker.on_pointer_update(200, 300, button1_down=True)
    assert msg1 is None

    # Mouse moved within threshold (delta ~2.8 px < 5 px)
    msg2 = tracker.on_pointer_update(202, 302, button1_down=True)
    assert msg2 is None

    # Mouse moved beyond threshold (delta > 5 px)
    msg3 = tracker.on_pointer_update(210, 310, button1_down=True)
    assert msg3 == "DRAG_START x=210 y=310"
    assert tracker.has_drag_detected()
    assert tracker.get_summary()["status"] == "PASS"
    assert tracker.get_summary()["last_drag"] == (210, 310)


def test_drag_tracker_single_event_per_drag():
    tracker = DragTracker(drag_threshold=5, candidate_keys=["Super"])
    tracker.on_key_press("Super")

    # Initial press
    tracker.on_pointer_update(100, 100, button1_down=True)

    # Cross threshold -> DRAG_START
    msg = tracker.on_pointer_update(110, 100, button1_down=True)
    assert msg == "DRAG_START x=110 y=100"

    # Continuing to drag should not fire additional DRAG_START events
    msg_continue = tracker.on_pointer_update(120, 100, button1_down=True)
    assert msg_continue is None
    assert tracker.drag_count == 1


def test_drag_tracker_release_resets_state():
    tracker = DragTracker(drag_threshold=5, candidate_keys=["Super"])
    tracker.on_key_press("Super")

    # First drag
    tracker.on_pointer_update(10, 10, button1_down=True)
    tracker.on_pointer_update(30, 30, button1_down=True)
    assert tracker.drag_count == 1

    # Release button
    tracker.on_pointer_update(30, 30, button1_down=False)
    assert not tracker.is_dragging

    # Second drag starts
    tracker.on_pointer_update(40, 40, button1_down=True)
    msg = tracker.on_pointer_update(60, 60, button1_down=True)
    assert msg == "DRAG_START x=60 y=60"
    assert tracker.drag_count == 2


def test_drag_tracker_key_release_cancels_drag():
    tracker = DragTracker(drag_threshold=5, candidate_keys=["Super"])
    tracker.on_key_press("Super")
    tracker.on_pointer_update(10, 10, button1_down=True)
    tracker.on_pointer_update(30, 30, button1_down=True)
    assert tracker.is_dragging

    # Key released -> stops drag
    tracker.on_key_release("Super")
    assert not tracker.is_dragging


def test_drag_tracker_format_summary():
    tracker = DragTracker(drag_threshold=5, candidate_keys=["Super"])
    summary_initial = tracker.format_summary()
    assert "FAIL" in summary_initial
    assert "Drags detected:       0" in summary_initial

    tracker.on_key_press("Super")
    tracker.on_pointer_update(10, 10, button1_down=True)
    tracker.on_pointer_update(50, 50, button1_down=True)

    summary_passed = tracker.format_summary()
    assert "PASS" in summary_passed
    assert "Drags detected:       1" in summary_passed
    assert "x=50 y=50" in summary_passed


def test_drag_tracker_custom_keys():
    tracker = DragTracker(drag_threshold=4, candidate_keys=["Right Ctrl"])
    # Pressing a key not in candidate keys
    tracker.on_key_press("Right Ctrl")
    tracker.on_pointer_update(0, 0, button1_down=True)
    msg = tracker.on_pointer_update(10, 0, button1_down=True)
    assert msg == "DRAG_START x=10 y=0"
    assert tracker.last_trigger_key == "Right Ctrl"


def test_run_x11_drag_listener_stop_check():
    import os

    if not os.environ.get("DISPLAY"):
        return

    try:
        import Xlib  # noqa: F401
    except ImportError:
        return

    from spikes.b_drag_and_cursor import run_x11_drag_listener

    tracker = DragTracker(drag_threshold=5)
    # Ensure it starts and stops immediately when stop_check returns True
    run_x11_drag_listener(
        drag_tracker=tracker,
        stop_check=lambda: True,
    )
