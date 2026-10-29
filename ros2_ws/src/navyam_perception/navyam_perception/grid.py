"""Arena grid maths: map-frame metres <-> organizer grid cells and labels.

Pure Python (no ROS imports) so the maze generator and unit tests can use it.

Convention (configurable, see docs/decisions.md D-006):
  * The grid origin is the arena corner on the entry side, given in the map frame.
  * Columns run along the grid's x axis and are lettered A, B, ..., Z, AA, AB, ...
  * Rows run along the grid's y axis and are numbered from ``row_base`` (default 1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def column_letters(index: int) -> str:
    """Spreadsheet-style column name: 0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    if index < 0:
        raise ValueError(f"column index must be >= 0, got {index}")
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


@dataclass(frozen=True)
class ArenaGrid:
    origin_x: float
    origin_y: float
    cell_m: float
    cols: int
    rows: int
    yaw: float = 0.0
    """Rotation of the grid's x axis in the map frame, radians (counter-clockwise)."""
    row_base: int = 1
    clamp_margin_m: float = 0.25
    """Points this far outside the arena are snapped to the nearest edge cell.

    SLAM error can put a survivor next to the outer wall a few cm outside the arena.
    """

    def __post_init__(self) -> None:
        if self.cell_m <= 0:
            raise ValueError("cell_m must be positive")
        if self.cols <= 0 or self.rows <= 0:
            raise ValueError("cols and rows must be positive")

    @property
    def width_m(self) -> float:
        return self.cols * self.cell_m

    @property
    def height_m(self) -> float:
        return self.rows * self.cell_m

    def to_grid_frame(self, x: float, y: float) -> tuple[float, float]:
        """Map-frame point -> metres along the grid's own axes from its origin."""
        dx, dy = x - self.origin_x, y - self.origin_y
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return c * dx + s * dy, -s * dx + c * dy

    def from_grid_frame(self, gx: float, gy: float) -> tuple[float, float]:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return self.origin_x + c * gx - s * gy, self.origin_y + s * gx + c * gy

    def cell_of(self, x: float, y: float) -> tuple[int, int] | None:
        """(col, row) containing the map-frame point, or None if it is outside the arena."""
        gx, gy = self.to_grid_frame(x, y)
        m = self.clamp_margin_m
        if not (-m <= gx < self.width_m + m and -m <= gy < self.height_m + m):
            return None
        col = min(max(int(math.floor(gx / self.cell_m)), 0), self.cols - 1)
        row = min(max(int(math.floor(gy / self.cell_m)), 0), self.rows - 1)
        return col, row

    def label(self, col: int, row: int) -> str:
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            raise ValueError(f"cell ({col}, {row}) is outside a {self.cols}x{self.rows} grid")
        return f"{column_letters(col)}{row + self.row_base}"

    def label_of(self, x: float, y: float) -> str | None:
        cell = self.cell_of(x, y)
        return None if cell is None else self.label(*cell)

    def cell_center(self, col: int, row: int) -> tuple[float, float]:
        return self.from_grid_frame((col + 0.5) * self.cell_m, (row + 0.5) * self.cell_m)
