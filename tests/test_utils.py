from __future__ import annotations

from mediagrab.utils import (
    clamp_text,
    human_duration,
    human_size,
    progress_bar,
    safe_filename,
)


def test_human_size() -> None:
    assert human_size(0) == "0 Б"
    assert human_size(None) == "0 Б"
    assert human_size(512) == "512 Б"
    assert human_size(1024) == "1,0 КБ"
    assert human_size(1536) == "1,5 КБ"
    assert human_size(50 * 1024 * 1024) == "50,0 МБ"


def test_human_duration() -> None:
    assert human_duration(None) == ""
    assert human_duration(0) == "00:00"
    assert human_duration(95) == "01:35"
    assert human_duration(3725) == "1:02:05"


def test_progress_bar() -> None:
    assert progress_bar(0, 10) == "░" * 10
    assert progress_bar(100, 10) == "▓" * 10
    assert progress_bar(50, 10) == "▓" * 5 + "░" * 5
    assert progress_bar(-10, 4) == "░" * 4
    assert progress_bar(999, 4) == "▓" * 4


def test_safe_filename_removes_bad_chars() -> None:
    assert safe_filename('a/b\\c:d*e?f"g<h>i|j') == "a b c d e f g h i j"
    assert safe_filename("   ") == "media"
    assert safe_filename("x" * 100, max_length=10) == "x" * 10


def test_clamp_text() -> None:
    assert clamp_text("abc", 10) == "abc"
    assert clamp_text("abcdefgh", 5) == "abcd…"
    assert len(clamp_text("abc", 0)) == 1
