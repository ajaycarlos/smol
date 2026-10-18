from spikes.a_key_hold import (
    CANDIDATE_KEYS,
    KeyHoldTracker,
    detect_session_type,
    pick_backend,
)


def test_detect_session_type():
    assert detect_session_type({"XDG_SESSION_TYPE": "x11"}) == "x11"
    assert detect_session_type({"XDG_SESSION_TYPE": "wayland"}) == "wayland"
    assert detect_session_type({"WAYLAND_DISPLAY": "wayland-0"}) == "wayland"
    assert detect_session_type({"DISPLAY": ":0"}) == "x11"
    assert detect_session_type({}) == "unknown"


def test_candidate_keys_list():
    assert CANDIDATE_KEYS == ["Ctrl+Alt", "Super", "Right Alt", "Right Ctrl"]


def test_tracker_press_release_and_timing():
    tracker = KeyHoldTracker()

    # Initial status should be FAIL for all until pressed and released
    summary = tracker.get_summary()
    for k in CANDIDATE_KEYS:
        assert summary[k] == "FAIL"

    # Press Super
    press_msg = tracker.on_press("Super", timestamp=100.0)
    assert press_msg == "PRESS Super"

    # Key repeat / duplicate press should return None
    dup_msg = tracker.on_press("Super", timestamp=100.1)
    assert dup_msg is None

    # Release Super after 350ms
    rel_msg = tracker.on_release("Super", timestamp=100.35)
    assert rel_msg == "RELEASE Super held=350ms"
    assert tracker.get_summary()["Super"] == "PASS"


def test_tracker_combo_ctrl_alt():
    tracker = KeyHoldTracker()

    # Pressing Left Ctrl alone should not trigger Ctrl+Alt
    assert tracker.on_raw_key_down("Control_L", timestamp=10.0) == []

    # Pressing Left Alt while Ctrl is held triggers PRESS Ctrl+Alt
    events = tracker.on_raw_key_down("Alt_L", timestamp=10.1)
    assert "PRESS Ctrl+Alt" in events

    # Releasing Alt triggers RELEASE Ctrl+Alt held=200ms
    rel_events = tracker.on_raw_key_up("Alt_L", timestamp=10.3)
    assert "RELEASE Ctrl+Alt held=200ms" in rel_events
    assert tracker.get_summary()["Ctrl+Alt"] == "PASS"


def test_tracker_right_ctrl_and_right_alt():
    tracker = KeyHoldTracker()

    # Right Ctrl
    assert "PRESS Right Ctrl" in tracker.on_raw_key_down("Control_R", timestamp=1.0)
    assert (
        "RELEASE Right Ctrl held=150ms"
        in tracker.on_raw_key_up("Control_R", timestamp=1.15)
    )
    assert tracker.get_summary()["Right Ctrl"] == "PASS"

    # Right Alt
    assert "PRESS Right Alt" in tracker.on_raw_key_down("Alt_R", timestamp=2.0)
    assert (
        "RELEASE Right Alt held=500ms"
        in tracker.on_raw_key_up("Alt_R", timestamp=2.5)
    )
    assert tracker.get_summary()["Right Alt"] == "PASS"


def test_pick_backend():
    assert pick_backend("x11", has_xlib=True, has_evdev=False) == "xlib"
    assert pick_backend("x11", has_xlib=False, has_evdev=True) == "evdev"
    assert pick_backend("wayland", has_xlib=False, has_evdev=True) == "evdev"
    assert (
        pick_backend("wayland", has_xlib=False, has_evdev=False)
        == "portal_or_unavailable"
    )


def test_tracker_all_passed_and_format_summary():
    tracker = KeyHoldTracker()
    assert not tracker.all_passed()

    # Pass all 4
    tracker.on_press("Super", timestamp=1.0)
    tracker.on_release("Super", timestamp=1.2)
    tracker.on_press("Right Ctrl", timestamp=1.0)
    tracker.on_release("Right Ctrl", timestamp=1.2)
    tracker.on_press("Right Alt", timestamp=1.0)
    tracker.on_release("Right Alt", timestamp=1.2)
    tracker.on_press("Ctrl+Alt", timestamp=1.0)
    tracker.on_release("Ctrl+Alt", timestamp=1.2)

    assert tracker.all_passed()
    summary_text = tracker.format_summary()
    for k in CANDIDATE_KEYS:
        assert f"{k}: PASS" in summary_text


def test_x11_query_keymap_stop_check():
    import os

    from spikes.a_key_hold import run_x11_query_keymap

    if not os.environ.get("DISPLAY"):
        return

    try:
        import Xlib  # noqa: F401
    except ImportError:
        return

    tracker = KeyHoldTracker()
    # Should exit immediately due to stop_check
    run_x11_query_keymap(tracker, stop_check=lambda: True)

