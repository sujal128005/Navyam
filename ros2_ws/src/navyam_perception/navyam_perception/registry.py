"""Survivor registry: turns noisy per-frame detections into a stable list of survivors.

Pure Python (no ROS imports). The ROS node in ``survivor_registry_node.py`` wraps it.

Rules:
  * A detection within ``merge_radius_m`` of an existing track updates that track
    (confidence-weighted mean position). Confirmed tracks are preferred when several match.
  * A track is confirmed once it has ``confirm_hits`` detections within ``confirm_window_s``.
  * Unconfirmed tracks with no detection for ``stale_s`` are dropped (false positives).
  * Confirmed tracks are never dropped; they are what the GCS shows and the judges score.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Track:
    id: int
    x: float
    y: float
    weight: float
    best_confidence: float
    first_seen: float
    last_seen: float
    hits: int = 0
    confirmed: bool = False
    confirmed_at: float | None = None
    recent: deque = field(default_factory=deque)

    def distance_to(self, x: float, y: float) -> float:
        return math.hypot(self.x - x, self.y - y)


class SurvivorRegistry:
    def __init__(
        self,
        merge_radius_m: float = 0.7,
        confirm_hits: int = 5,
        confirm_window_s: float = 1.5,
        stale_s: float = 5.0,
        min_confidence: float = 0.4,
    ) -> None:
        if merge_radius_m <= 0 or confirm_hits < 1 or confirm_window_s <= 0:
            raise ValueError("invalid registry settings")
        self.merge_radius_m = merge_radius_m
        self.confirm_hits = confirm_hits
        self.confirm_window_s = confirm_window_s
        self.stale_s = stale_s
        self.min_confidence = min_confidence
        self._tracks: list[Track] = []
        self._next_id = 1

    @property
    def confirmed(self) -> list[Track]:
        return [t for t in self._tracks if t.confirmed]

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks)

    def add(self, x: float, y: float, confidence: float, t: float) -> Track | None:
        """Record one detection in the map frame. Returns the track if this detection confirmed it."""
        if confidence < self.min_confidence or not (math.isfinite(x) and math.isfinite(y)):
            return None
        self.prune(t)
        track = self._match(x, y)
        if track is None:
            track = Track(
                id=self._next_id, x=x, y=y, weight=0.0, best_confidence=confidence,
                first_seen=t, last_seen=t,
            )
            self._next_id += 1
            self._tracks.append(track)

        total = track.weight + confidence
        track.x = (track.x * track.weight + x * confidence) / total
        track.y = (track.y * track.weight + y * confidence) / total
        track.weight = total
        track.best_confidence = max(track.best_confidence, confidence)
        track.last_seen = t
        track.hits += 1

        if track.confirmed:
            return None
        track.recent.append(t)
        while track.recent and t - track.recent[0] > self.confirm_window_s:
            track.recent.popleft()
        if len(track.recent) >= self.confirm_hits:
            track.confirmed = True
            track.confirmed_at = t
            track.recent.clear()
            return track
        return None

    def prune(self, t: float) -> None:
        self._tracks = [
            tr for tr in self._tracks if tr.confirmed or t - tr.last_seen <= self.stale_s
        ]

    def _match(self, x: float, y: float) -> Track | None:
        candidates = [tr for tr in self._tracks if tr.distance_to(x, y) <= self.merge_radius_m]
        if not candidates:
            return None
        return min(candidates, key=lambda tr: (not tr.confirmed, tr.distance_to(x, y)))
