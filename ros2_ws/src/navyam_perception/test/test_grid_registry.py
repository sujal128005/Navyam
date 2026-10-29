import math
import unittest

from navyam_perception.grid import ArenaGrid, column_letters
from navyam_perception.registry import SurvivorRegistry


class ColumnLettersTest(unittest.TestCase):
    def test_letters(self):
        self.assertEqual([column_letters(i) for i in (0, 1, 25, 26, 27, 51, 52)],
                         ["A", "B", "Z", "AA", "AB", "AZ", "BA"])
        with self.assertRaises(ValueError):
            column_letters(-1)


class ArenaGridTest(unittest.TestCase):
    def setUp(self):
        self.g = ArenaGrid(origin_x=1.5, origin_y=-7.5, cell_m=1.0, cols=15, rows=15)

    def test_cell_and_label(self):
        self.assertEqual(self.g.cell_of(1.6, -7.4), (0, 0))
        self.assertEqual(self.g.label_of(1.6, -7.4), "A1")
        self.assertEqual(self.g.label_of(4.2, 0.0), "C8")
        self.assertEqual(self.g.label_of(16.4, 7.4), "O15")

    def test_outside_and_clamp(self):
        self.assertEqual(self.g.cell_of(1.4, 0.0), (0, 7))   # 10 cm outside: snapped
        self.assertIsNone(self.g.cell_of(0.0, 0.0))          # launch point is outside the arena
        self.assertIsNone(self.g.cell_of(20.0, 0.0))

    def test_rotated_grid_round_trip(self):
        g = ArenaGrid(origin_x=2.0, origin_y=1.0, cell_m=2.0, cols=7, rows=7, yaw=math.radians(30))
        for col, row in [(0, 0), (3, 4), (6, 6)]:
            x, y = g.cell_center(col, row)
            self.assertEqual(g.cell_of(x, y), (col, row))

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            ArenaGrid(0, 0, 0.0, 3, 3)
        with self.assertRaises(ValueError):
            self.g.label(15, 0)


class SurvivorRegistryTest(unittest.TestCase):
    def test_confirms_after_enough_hits_in_window(self):
        r = SurvivorRegistry(confirm_hits=5, confirm_window_s=1.5)
        confirmed = [r.add(3.0 + 0.05 * i, 2.0, 0.8, t=0.2 * i) for i in range(5)]
        self.assertEqual(confirmed[:4], [None] * 4)
        self.assertIsNotNone(confirmed[4])
        self.assertEqual(len(r.confirmed), 1)
        self.assertAlmostEqual(r.confirmed[0].x, 3.1, places=6)

    def test_sparse_hits_do_not_confirm(self):
        r = SurvivorRegistry(confirm_hits=3, confirm_window_s=1.0, stale_s=10)
        for i in range(6):
            r.add(1.0, 1.0, 0.9, t=1.1 * i)
        self.assertEqual(r.confirmed, [])

    def test_two_people_far_apart_are_two_tracks(self):
        r = SurvivorRegistry(confirm_hits=2)
        for i in range(2):
            r.add(0.0, 0.0, 0.9, t=0.1 * i)
            r.add(3.0, 0.0, 0.9, t=0.1 * i + 0.05)
        self.assertEqual(len(r.confirmed), 2)

    def test_stale_false_positive_dropped_confirmed_kept(self):
        r = SurvivorRegistry(confirm_hits=2, stale_s=2.0)
        r.add(0, 0, 0.9, 0.0)
        r.add(0, 0, 0.9, 0.1)            # confirmed
        r.add(5, 5, 0.9, 0.2)            # one-off
        r.prune(10.0)
        self.assertEqual([(t.x, t.y) for t in r.tracks], [(0, 0)])

    def test_low_confidence_and_nan_ignored(self):
        r = SurvivorRegistry(min_confidence=0.5)
        self.assertIsNone(r.add(1, 1, 0.3, 0))
        self.assertIsNone(r.add(float("nan"), 1, 0.9, 0))
        self.assertEqual(r.tracks, [])

    def test_confirmed_track_absorbs_nearby_detections(self):
        r = SurvivorRegistry(confirm_hits=2, merge_radius_m=0.7)
        r.add(0, 0, 0.9, 0.0)
        r.add(0, 0, 0.9, 0.1)
        r.add(0.5, 0, 0.9, 0.2)
        self.assertEqual(len(r.tracks), 1)


if __name__ == "__main__":
    unittest.main()
