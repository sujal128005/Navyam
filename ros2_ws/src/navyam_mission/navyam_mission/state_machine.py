"""Mission state machine: start -> take off -> explore -> return to exit -> land.

Pure Python (no ROS imports). ``Mission.step`` takes a snapshot of the world (``Inputs``)
and returns the actions to execute; ``mission_node.py`` executes them over ROS.

The operator may only start and abort (NIDAR brief section 4). Everything else is decided here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ArduCopter flight modes (MAVLink COPTER_MODE)
COPTER_MODE_GUIDED = 4
COPTER_MODE_LAND = 9


class Phase(str, Enum):
    IDLE = "IDLE"
    TAKEOFF = "TAKEOFF"
    EXPLORE = "EXPLORE"
    RETURN = "RETURN"
    LAND = "LAND"
    DONE = "DONE"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class SetMode:
    mode: int


@dataclass(frozen=True)
class Arm:
    arm: bool


@dataclass(frozen=True)
class Takeoff:
    alt_m: float


@dataclass(frozen=True)
class Explore:
    enable: bool


@dataclass(frozen=True)
class NavEnable:
    """Allow the cmd_vel bridge to forward Nav2 velocity commands to ArduPilot."""
    enable: bool


@dataclass(frozen=True)
class NavigateHome:
    pass


@dataclass(frozen=True)
class CancelNav:
    pass


@dataclass
class MissionConfig:
    takeoff_alt_m: float = 1.1
    takeoff_reached_frac: float = 0.85
    arm_timeout_s: float = 5.0
    takeoff_timeout_s: float = 25.0
    explore_budget_s: float = 600.0
    min_battery_pct: float = 35.0
    expected_survivors: int = 6
    stall_s: float = 30.0
    stall_growth_cells: int = 50
    home_radius_m: float = 0.5
    return_timeout_s: float = 240.0
    nav_retries: int = 2


@dataclass
class Inputs:
    now: float
    start: bool = False
    abort: bool = False
    abort_reason: str = "operator abort"
    armed: bool = False
    altitude_m: float | None = None
    battery_pct: float | None = None
    survivors: int = 0
    known_cells: int = 0
    dist_home_m: float | None = None
    nav_failed: bool = False


class Mission:
    def __init__(self, cfg: MissionConfig | None = None) -> None:
        self.cfg = cfg or MissionConfig()
        self.phase = Phase.IDLE
        self.reason = "waiting for start"
        self.t_start: float | None = None
        self.t_phase: float | None = None
        self._t_growth: float | None = None
        self._best_known = 0
        self._nav_attempts = 0

    def elapsed(self, now: float) -> float:
        return 0.0 if self.t_start is None else now - self.t_start

    def step(self, i: Inputs) -> list:
        if i.abort and self.phase not in (Phase.IDLE, Phase.DONE, Phase.ABORTED):
            return self._enter(Phase.ABORTED, i.now, i.abort_reason,
                               [Explore(False), CancelNav(), NavEnable(False), SetMode(COPTER_MODE_LAND)])
        handler = {
            Phase.IDLE: self._idle,
            Phase.TAKEOFF: self._takeoff,
            Phase.EXPLORE: self._explore,
            Phase.RETURN: self._return,
            Phase.LAND: self._land,
        }.get(self.phase)
        return handler(i) if handler else []

    def _enter(self, phase: Phase, now: float, reason: str, actions: list) -> list:
        self.phase, self.reason, self.t_phase = phase, reason, now
        return actions

    def _idle(self, i: Inputs) -> list:
        if not i.start:
            return []
        self.t_start = i.now
        return self._enter(Phase.TAKEOFF, i.now, "operator start",
                           [SetMode(COPTER_MODE_GUIDED), Arm(True), Takeoff(self.cfg.takeoff_alt_m)])

    def _takeoff(self, i: Inputs) -> list:
        cfg, in_phase = self.cfg, i.now - self.t_phase
        if i.armed and i.altitude_m is not None and i.altitude_m >= cfg.takeoff_alt_m * cfg.takeoff_reached_frac:
            self._best_known, self._t_growth = i.known_cells, i.now
            return self._enter(Phase.EXPLORE, i.now, "takeoff altitude reached", [NavEnable(True), Explore(True)])
        if not i.armed and in_phase > cfg.arm_timeout_s:
            return self._enter(Phase.ABORTED, i.now, "arming failed", [SetMode(COPTER_MODE_LAND)])
        if in_phase > cfg.takeoff_timeout_s:
            return self._enter(Phase.ABORTED, i.now, "takeoff timeout", [SetMode(COPTER_MODE_LAND)])
        return []

    def _explore(self, i: Inputs) -> list:
        cfg = self.cfg
        if i.known_cells >= self._best_known + cfg.stall_growth_cells:
            self._best_known, self._t_growth = i.known_cells, i.now

        reason = None
        if cfg.expected_survivors > 0 and i.survivors >= cfg.expected_survivors:
            reason = f"all {cfg.expected_survivors} survivors found"
        elif i.battery_pct is not None and i.battery_pct < cfg.min_battery_pct:
            reason = f"battery {i.battery_pct:.0f}% below {cfg.min_battery_pct:.0f}%"
        elif i.now - self.t_phase >= cfg.explore_budget_s:
            reason = "exploration time budget used"
        elif i.now - self._t_growth >= cfg.stall_s:
            reason = "map stopped growing: exploration complete"
        if reason is None:
            return []
        self._nav_attempts = 1
        return self._enter(Phase.RETURN, i.now, reason, [Explore(False), NavigateHome()])

    def _return(self, i: Inputs) -> list:
        cfg = self.cfg
        land = [NavEnable(False), SetMode(COPTER_MODE_LAND)]
        if i.dist_home_m is not None and i.dist_home_m <= cfg.home_radius_m:
            return self._enter(Phase.LAND, i.now, "reached exit", [CancelNav()] + land)
        if i.nav_failed:
            if self._nav_attempts <= cfg.nav_retries:
                self._nav_attempts += 1
                self.reason = f"retrying return to exit ({self._nav_attempts - 1}/{cfg.nav_retries})"
                return [NavigateHome()]
            return self._enter(Phase.LAND, i.now, "could not reach exit, landing in place", land)
        if i.now - self.t_phase > cfg.return_timeout_s:
            return self._enter(Phase.LAND, i.now, "return timeout, landing in place", [CancelNav()] + land)
        return []

    def _land(self, i: Inputs) -> list:
        if not i.armed:
            return self._enter(Phase.DONE, i.now, "landed and disarmed", [])
        return []
