import math
import unittest

from navyam_mission.state_machine import (
    COPTER_MODE_GUIDED, COPTER_MODE_LAND, Arm, CancelNav, Explore, Inputs, Mission, MissionConfig,
    NavEnable, NavigateHome, Phase, SetMode, Takeoff,
)
from navyam_mission.velocity import VelocityLimits, body_command, earth_to_body, yaw_from_quaternion


def flying(mission: Mission, now: float = 10.0, known: int = 100) -> None:
    """Drive a mission into EXPLORE."""
    mission.step(Inputs(now=0.0, start=True))
    mission.step(Inputs(now=now, armed=True, altitude_m=1.1, known_cells=known))
    assert mission.phase is Phase.EXPLORE


class MissionTest(unittest.TestCase):
    def test_idle_until_start(self):
        m = Mission()
        self.assertEqual(m.step(Inputs(now=0.0)), [])
        self.assertIs(m.phase, Phase.IDLE)

    def test_start_sends_guided_arm_takeoff(self):
        m = Mission(MissionConfig(takeoff_alt_m=1.2))
        actions = m.step(Inputs(now=0.0, start=True))
        self.assertEqual(actions, [SetMode(COPTER_MODE_GUIDED), Arm(True), Takeoff(1.2)])
        self.assertIs(m.phase, Phase.TAKEOFF)

    def test_takeoff_waits_for_altitude_then_explores(self):
        m = Mission()
        m.step(Inputs(now=0.0, start=True))
        self.assertEqual(m.step(Inputs(now=2.0, armed=True, altitude_m=0.5)), [])
        self.assertEqual(m.step(Inputs(now=4.0, armed=True, altitude_m=1.0)), [NavEnable(True), Explore(True)])
        self.assertIs(m.phase, Phase.EXPLORE)

    def test_arming_failure_aborts(self):
        m = Mission(MissionConfig(arm_timeout_s=5))
        m.step(Inputs(now=0.0, start=True))
        self.assertEqual(m.step(Inputs(now=6.0, armed=False)), [SetMode(COPTER_MODE_LAND)])
        self.assertIs(m.phase, Phase.ABORTED)
        self.assertEqual(m.reason, "arming failed")

    def test_returns_when_all_survivors_found(self):
        m = Mission(MissionConfig(expected_survivors=6))
        flying(m)
        self.assertEqual(m.step(Inputs(now=20.0, armed=True, survivors=5, known_cells=500)), [])
        self.assertEqual(m.step(Inputs(now=21.0, armed=True, survivors=6, known_cells=600)),
                         [Explore(False), NavigateHome()])
        self.assertIs(m.phase, Phase.RETURN)

    def test_returns_on_low_battery_and_time_budget(self):
        m = Mission(MissionConfig(min_battery_pct=35))
        flying(m)
        m.step(Inputs(now=20.0, armed=True, battery_pct=30.0, known_cells=500))
        self.assertIs(m.phase, Phase.RETURN)
        self.assertIn("battery", m.reason)

        m = Mission(MissionConfig(explore_budget_s=100, stall_s=1000))
        flying(m, now=10.0)
        m.step(Inputs(now=109.0, armed=True, known_cells=100))
        self.assertIs(m.phase, Phase.EXPLORE)
        m.step(Inputs(now=110.0, armed=True, known_cells=100))
        self.assertIs(m.phase, Phase.RETURN)

    def test_map_growth_postpones_stall(self):
        m = Mission(MissionConfig(stall_s=30, stall_growth_cells=50))
        flying(m, now=10.0, known=100)
        m.step(Inputs(now=35.0, armed=True, known_cells=200))   # grew: timer reset at 35
        m.step(Inputs(now=60.0, armed=True, known_cells=210))   # small growth, ignored
        self.assertIs(m.phase, Phase.EXPLORE)
        m.step(Inputs(now=65.0, armed=True, known_cells=220))
        self.assertIs(m.phase, Phase.RETURN)
        self.assertIn("exploration complete", m.reason)

    def test_return_reaches_exit_and_lands(self):
        m = Mission(MissionConfig(expected_survivors=1))
        flying(m)
        m.step(Inputs(now=20.0, armed=True, survivors=1))
        self.assertEqual(m.step(Inputs(now=30.0, armed=True, dist_home_m=0.3)),
                         [CancelNav(), NavEnable(False), SetMode(COPTER_MODE_LAND)])
        self.assertIs(m.phase, Phase.LAND)
        m.step(Inputs(now=40.0, armed=False))
        self.assertIs(m.phase, Phase.DONE)

    def test_return_retries_then_lands_in_place(self):
        m = Mission(MissionConfig(expected_survivors=1, nav_retries=2))
        flying(m)
        m.step(Inputs(now=20.0, armed=True, survivors=1))
        self.assertEqual(m.step(Inputs(now=25.0, armed=True, dist_home_m=5, nav_failed=True)), [NavigateHome()])
        self.assertEqual(m.step(Inputs(now=30.0, armed=True, dist_home_m=5, nav_failed=True)), [NavigateHome()])
        self.assertEqual(m.step(Inputs(now=35.0, armed=True, dist_home_m=5, nav_failed=True)),
                         [NavEnable(False), SetMode(COPTER_MODE_LAND)])
        self.assertIs(m.phase, Phase.LAND)

    def test_abort_from_any_flying_phase(self):
        for phase_setup in ("takeoff", "explore"):
            m = Mission()
            m.step(Inputs(now=0.0, start=True))
            if phase_setup == "explore":
                m.step(Inputs(now=5.0, armed=True, altitude_m=1.1))
            actions = m.step(Inputs(now=6.0, abort=True, armed=True))
            self.assertIs(m.phase, Phase.ABORTED)
            self.assertEqual(actions[-1], SetMode(COPTER_MODE_LAND))
        idle = Mission()
        self.assertEqual(idle.step(Inputs(now=0.0, abort=True)), [])
        self.assertIs(idle.phase, Phase.IDLE)


class VelocityTest(unittest.TestCase):
    def test_speed_cap_keeps_direction(self):
        vx, vy, vz, wz = body_command(1.0, 1.0, 2.0, 1.1, 1.1, VelocityLimits(max_xy=0.5, max_yaw_rate=0.8))
        self.assertAlmostEqual(math.hypot(vx, vy), 0.5)
        self.assertAlmostEqual(vx, vy)
        self.assertEqual((vz, wz), (0.0, 0.8))

    def test_altitude_hold(self):
        lim = VelocityLimits(kz=1.0, max_vz=0.3)
        self.assertAlmostEqual(body_command(0, 0, 0, 1.0, 1.1, lim)[2], 0.1)
        self.assertAlmostEqual(body_command(0, 0, 0, 2.0, 1.1, lim)[2], -0.3)
        self.assertEqual(body_command(0, 0, 0, None, 1.1, lim)[2], 0.0)

    def test_frames(self):
        yaw = yaw_from_quaternion(0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4))
        self.assertAlmostEqual(yaw, math.pi / 2)
        bx, by = earth_to_body(0.0, 1.0, yaw)   # moving north while facing north = forward
        self.assertAlmostEqual(bx, 1.0)
        self.assertAlmostEqual(by, 0.0)


if __name__ == "__main__":
    unittest.main()
