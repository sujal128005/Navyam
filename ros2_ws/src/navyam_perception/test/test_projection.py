import unittest

import numpy as np

from navyam_perception.projection import box_depth_m, pixel_to_point


class ProjectionTest(unittest.TestCase):
    def test_principal_point_projects_straight_ahead(self):
        self.assertEqual(pixel_to_point(320, 240, 2.0, 600, 600, 320, 240), (0.0, 0.0, 2.0))
        x, y, z = pixel_to_point(620, 90, 3.0, 600, 600, 320, 240)
        self.assertAlmostEqual(x, 1.5)
        self.assertAlmostEqual(y, -0.75)

    def test_box_depth_uses_centre_and_ignores_holes(self):
        depth = np.full((480, 640), 4000, dtype=np.uint16)   # background wall at 4 m (mm units)
        depth[200:300, 250:350] = 2000                       # person at 2 m
        depth[240:250, 290:300] = 0                          # sensor holes
        self.assertAlmostEqual(box_depth_m(depth, (240, 190, 360, 310), 0.001), 2.0)

    def test_box_depth_none_when_no_valid_pixels(self):
        depth = np.zeros((100, 100), dtype=np.float32)
        self.assertIsNone(box_depth_m(depth, (10, 10, 50, 50), 1.0))
        self.assertIsNone(box_depth_m(depth, (200, 200, 300, 300), 1.0))  # box off image


if __name__ == "__main__":
    unittest.main()
