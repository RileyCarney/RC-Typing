"""Keystroke replay and typing metrics computation."""

from __future__ import annotations

import math
from typing import List, Tuple
from rctyping_common.models import KeystrokeEvent, Metrics


def replay_keystrokes(events: List[KeystrokeEvent]) -> str:
    """Replay keystroke events into the resulting text buffer."""
    buffer: List[str] = []
    for ev in events:
        if ev.type != "keydown":
            continue
        key = ev.key
        if key == "Backspace":
            if buffer:
                buffer.pop()
        elif key == "Enter":
            buffer.append("\n")
        elif key == "Tab":
            buffer.extend("    ")
        elif len(key) == 1:
            buffer.append(key)
    return "".join(buffer)


def compute_metrics(
    target_text: str,
    events: List[KeystrokeEvent],
    server_duration_ms: int,
    max_clock_skew_ms: int = 4000,
) -> Tuple[Metrics, str]:
    """Compute WPM, accuracy, consistency and reconstructed string."""
    keydown_events = [e for e in events if e.type == "keydown"]
    if not keydown_events:
        return (
            Metrics(
                net_wpm=0.0,
                raw_wpm=0.0,
                accuracy=0.0,
                consistency=0.0,
                duration_ms=server_duration_ms,
                chars_total=0,
                chars_correct=0,
                chars_incorrect=0,
            ),
            "",
        )

    # Determine duration (floor at 1ms only to prevent division by zero; no artificial WPM cap)
    first_t = keydown_events[0].t_ms
    last_t = keydown_events[-1].t_ms
    client_duration = max(1, last_t - first_t)

    # Clamp client duration if skew is unreasonable (never shrink below keystroke span)
    if abs(client_duration - server_duration_ms) > max_clock_skew_ms:
        duration_ms = max(client_duration, server_duration_ms)
    else:
        duration_ms = client_duration

    duration_minutes = max(1, duration_ms) / 60000.0

    # Replay text
    reconstructed = replay_keystrokes(keydown_events)

    # Count correct characters against target
    min_len = min(len(reconstructed), len(target_text))
    chars_correct = sum(1 for i in range(min_len) if reconstructed[i] == target_text[i])
    chars_incorrect = len(reconstructed) - chars_correct

    # Total keystrokes including backspaces and printable chars
    # Tab contributes 4 spaces into reconstructed text, so each Tab accounts for 4 characters
    chars_total = sum(
        4 if e.key == "Tab" else 1
        for e in keydown_events
        if len(e.key) == 1 or e.key in ("Enter", "Backspace", "Tab")
    )
    # Ensure chars_total is at least chars_correct to avoid inverted accuracy
    chars_total = max(chars_total, chars_correct)

    # Net WPM: (correct characters / 5) / minutes
    net_wpm = round((chars_correct / 5.0) / duration_minutes, 1)

    # Raw WPM: (total characters typed / 5) / minutes
    raw_wpm = round((chars_total / 5.0) / duration_minutes, 1)

    # Accuracy ratio bounded strictly between 0.0 and 1.0
    raw_accuracy = chars_correct / max(1, len(reconstructed))
    accuracy = round(max(0.0, min(1.0, raw_accuracy)), 3)

    # Inter-key intervals (IKIs) for consistency calculation
    ikis: List[float] = []
    for i in range(1, len(keydown_events)):
        delta = keydown_events[i].t_ms - keydown_events[i - 1].t_ms
        if delta >= 0:
            ikis.append(float(delta))

    if ikis:
        mean_iki = sum(ikis) / len(ikis)
        variance = sum((x - mean_iki) ** 2 for x in ikis) / len(ikis)
        stddev = math.sqrt(variance)
        cv = stddev / max(1.0, mean_iki)
        consistency = round(max(0.0, min(1.0, 1.0 - cv * 0.5)), 2)
    else:
        consistency = 0.0

    metrics = Metrics(
        net_wpm=net_wpm,
        raw_wpm=raw_wpm,
        accuracy=accuracy,
        consistency=consistency,
        duration_ms=duration_ms,
        chars_total=chars_total,
        chars_correct=chars_correct,
        chars_incorrect=chars_incorrect,
    )

    return metrics, reconstructed
