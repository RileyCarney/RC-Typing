"""Anti-cheat and keystroke plausibility heuristics."""

from __future__ import annotations

import math
from typing import List, Tuple
from rctyping_common.models import KeystrokeEvent


def evaluate_keystroke_integrity(
    events: List[KeystrokeEvent],
    server_duration_ms: int,
    min_human_iki_ms: float = 35.0,
    min_iki_stddev_ms: float = 4.0,
    max_clock_skew_ms: int = 4000,
) -> Tuple[str, List[str]]:
    """Analyze keystroke event dynamics for automation, macros, or manipulation.

    Returns:
        (integrity_status, list_of_flags)
        integrity_status is either 'clean' or 'flagged'.
    """
    flags: List[str] = []
    keydown_events = [e for e in events if e.type == "keydown"]

    if not keydown_events:
        return "flagged", ["no_events"]

    if len(keydown_events) < 10:
        flags.append("insufficient_events")

    # 1. Untrusted browser events (synthetic script dispatch)
    if any(not e.is_trusted for e in events):
        flags.append("untrusted_browser_event")

    # 2. Timing bounds and clock skew
    client_duration = keydown_events[-1].t_ms - keydown_events[0].t_ms
    skew = abs(client_duration - server_duration_ms)
    if skew > max_clock_skew_ms:
        flags.append(f"clock_skew_excessive_{skew}ms")

    # 3. Inter-keystroke intervals (IKIs)
    ikis: List[float] = []
    for i in range(1, len(keydown_events)):
        delta = keydown_events[i].t_ms - keydown_events[i - 1].t_ms
        if delta >= 0:
            ikis.append(float(delta))

    if ikis:
        mean_iki = sum(ikis) / len(ikis)
        variance = sum((x - mean_iki) ** 2 for x in ikis) / len(ikis)
        stddev_iki = math.sqrt(variance)

        # Inhuman sustained speed (> 28.5 chars/sec)
        if mean_iki < min_human_iki_ms:
            flags.append(f"inhuman_speed_iki_{mean_iki:.1f}ms")

        # Suspiciously uniform timing (macro loop without realistic human jitter)
        if len(ikis) >= 20 and stddev_iki < min_iki_stddev_ms:
            flags.append(f"uniform_timing_loop_stddev_{stddev_iki:.2f}ms")

    # 4. Key Dwell Times (keydown to keyup)
    dwells: List[float] = []
    keyup_dict = {}
    for e in events:
        if e.type == "keyup":
            keyup_dict.setdefault(e.key, []).append(e.t_ms)

    for kd in keydown_events:
        ku_list = keyup_dict.get(kd.key)
        if ku_list:
            # Find earliest keyup after keydown
            matching = [t for t in ku_list if t >= kd.t_ms]
            if matching:
                dwells.append(float(matching[0] - kd.t_ms))

    if len(dwells) >= 20:
        # Check if all dwell times are identical (macro device with fixed duration)
        unique_dwells = set(round(d, 1) for d in dwells)
        if len(unique_dwells) == 1:
            flags.append("uniform_dwell_fixed_macro")

    integrity = "clean" if not flags else "flagged"
    return integrity, flags
