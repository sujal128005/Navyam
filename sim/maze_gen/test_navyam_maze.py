import math
import unittest
import xml.etree.ElementTree as ET

import navyam_maze as nm


class MazeGeneratorTest(unittest.TestCase):
    def make(self, **kw) -> nm.Maze:
        return nm.generate(nm.MazeSpec(seed=kw.pop("seed", 3), **kw))

    def test_every_cell_reachable_from_entry(self):
        for seed in range(20):
            maze = self.make(seed=seed)
            self.assertEqual(len(maze.reachable_cells()), maze.n * maze.n, f"seed {seed}")

    def test_outer_wall_closed_except_entry(self):
        maze = self.make()
        n = maze.n
        for j in range(n):
            self.assertEqual(maze.vwalls[0][j], j != maze.entry_row)
            self.assertTrue(maze.vwalls[n][j])
        for i in range(n):
            self.assertTrue(maze.hwalls[i][0])
            self.assertTrue(maze.hwalls[i][n])

    def test_rooms_are_open_inside_and_do_not_touch(self):
        maze = self.make(rooms=6)
        k = maze.spec.room_cells
        self.assertEqual(len(maze.rooms), 6)
        for ri, rj in maze.rooms:
            for i in range(ri + 1, ri + k):
                for j in range(rj, rj + k):
                    self.assertFalse(maze.vwalls[i][j])
            for i in range(ri, ri + k):
                for j in range(rj + 1, rj + k):
                    self.assertFalse(maze.hwalls[i][j])
        for a, (ai, aj) in enumerate(maze.rooms):
            for bi, bj in maze.rooms[a + 1:]:
                self.assertTrue(abs(ai - bi) > k or abs(aj - bj) > k)

    def test_survivors_in_distinct_rooms_with_matching_labels(self):
        maze = self.make(survivors=6, rooms=6)
        rooms = {maze.room_of(s.col, s.row) for s in maze.survivors}
        self.assertEqual(len(rooms), 6)
        self.assertNotIn(None, rooms)
        for s in maze.survivors:
            self.assertEqual(maze.grid.label_of(s.x, s.y), s.label)

    def test_entry_faces_launch_point(self):
        maze = self.make()
        # Entry opening centred on y = 0, standoff metres in front of the drone.
        x, y = maze.grid.cell_center(0, maze.entry_row)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(x, maze.spec.standoff_m + maze.spec.cell_m / 2)

    def test_more_survivors_than_rooms_use_dead_ends(self):
        maze = self.make(rooms=3, survivors=5, braid=0.0)
        self.assertEqual(len(maze.survivors), 5)
        in_rooms = [s for s in maze.survivors if maze.room_of(s.col, s.row) is not None]
        self.assertEqual(len(in_rooms), 3)

    def test_same_seed_same_maze(self):
        a, b = self.make(seed=11), self.make(seed=11)
        self.assertEqual(a.vwalls, b.vwalls)
        self.assertEqual(a.hwalls, b.hwalls)
        self.assertEqual([s.label for s in a.survivors], [s.label for s in b.survivors])

    def test_invalid_specs_rejected(self):
        with self.assertRaises(ValueError):
            nm.generate(nm.MazeSpec(arena_m=15.0, cell_m=2.0))  # 7.5 cells
        with self.assertRaises(ValueError):
            nm.generate(nm.MazeSpec(rooms=40, seed=1))

    def test_sdf_is_valid_xml_with_walls_and_survivors(self):
        maze = self.make()
        root = ET.fromstring(nm.to_sdf(maze, "nidar_test", nm.FUEL_SURVIVOR_URI))
        world = root.find("world")
        self.assertEqual(world.get("name"), "nidar_test")
        arena = [m for m in world.findall("model") if m.get("name") == "arena"][0]
        self.assertEqual(len(arena.findall("link")), len(nm.wall_segments(maze)))
        self.assertEqual(len(world.findall("include")), len(maze.survivors))
        offline = ET.fromstring(nm.to_sdf(maze, "nidar_test", None))
        names = {m.get("name") for m in offline.find("world").findall("model")}
        self.assertTrue({s.name for s in maze.survivors} <= names)

    def test_wall_segments_stay_inside_arena(self):
        maze = self.make()
        g, t = maze.grid, maze.spec.wall_thickness_m
        for cx, cy, sx, sy in nm.wall_segments(maze):
            self.assertGreaterEqual(cx - sx / 2, g.origin_x - t)
            self.assertLessEqual(cx + sx / 2, g.origin_x + g.width_m + t)
            self.assertGreaterEqual(cy - sy / 2, g.origin_y - t)
            self.assertLessEqual(cy + sy / 2, g.origin_y + g.height_m + t)
            self.assertTrue(math.isclose(min(sx, sy), t))

    def test_ascii_has_one_line_per_row_and_border(self):
        maze = self.make()
        self.assertEqual(len(nm.to_ascii(maze).splitlines()), 2 * maze.n + 1)


if __name__ == "__main__":
    unittest.main()
