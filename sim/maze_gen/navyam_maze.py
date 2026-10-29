#!/usr/bin/env python3
"""Generate NIDAR AirMouse-style maze worlds for Gazebo (Garden/Harmonic) with ArduPilot SITL.

What the brief fixes and this generator follows:
  * square arena, at most 15 m x 15 m, on a modular grid;
  * corridors of uniform width >= 1 m (one grid cell), 2 m x 2 m rooms;
  * 8 ft (2.44 m) wall height; one entry, which is also the exit;
  * up to 6 survivors inside rooms.

Layout: rooms are placed first as k x k cell blocks (k = room_m / cell_m). A randomized
Kruskal spanning tree then connects every cell and room, so everything is reachable. Finally
a fraction of walls (``braid``) is removed to add loops, as in a real building.

World frame = map frame: the drone spawns at the origin facing +x, ``standoff_m`` in front of
the entry opening in the arena's west wall.

Outputs (for ``--out sim/worlds/NAME``):
  NAME.sdf          Gazebo world
  NAME.yaml         layout metadata + survivor ground truth (for scoring runs)
  NAME.params.yaml  ROS 2 parameters (grid_*) for navyam nodes

Pure Python 3.10+, no third-party packages.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ros2_ws" / "src" / "navyam_perception"))
from navyam_perception.grid import ArenaGrid  # noqa: E402

FUEL_SURVIVOR_URI = "https://fuel.gazebosim.org/1.0/OpenRobotics/models/Rescue Randy"


@dataclass
class MazeSpec:
    arena_m: float = 15.0
    cell_m: float = 1.0
    room_m: float = 2.0
    rooms: int = 6
    survivors: int = 6
    braid: float = 0.15
    wall_height_m: float = 2.44
    wall_thickness_m: float = 0.05
    standoff_m: float = 1.5
    seed: int | None = None

    @property
    def n(self) -> int:
        return int(round(self.arena_m / self.cell_m))

    @property
    def room_cells(self) -> int:
        return max(1, int(round(self.room_m / self.cell_m)))

    def validate(self) -> None:
        if self.cell_m <= 0 or self.arena_m <= 0:
            raise ValueError("arena_m and cell_m must be positive")
        if abs(self.n * self.cell_m - self.arena_m) > 1e-6:
            raise ValueError(f"arena_m ({self.arena_m}) must be a whole number of cells ({self.cell_m} m)")
        if self.room_cells > self.n:
            raise ValueError("rooms are larger than the arena")
        if not 0.0 <= self.braid <= 1.0:
            raise ValueError("braid must be between 0 and 1")
        if self.rooms < 0 or self.survivors < 0:
            raise ValueError("rooms and survivors must be >= 0")


@dataclass
class Survivor:
    name: str
    x: float
    y: float
    yaw: float
    col: int
    row: int
    label: str


@dataclass
class Maze:
    spec: MazeSpec
    # vwalls[i][j]: wall on the line x = i (0..n), alongside cell row j (0..n-1)
    vwalls: list[list[bool]]
    # hwalls[i][j]: wall on the line y = j (0..n), alongside cell column i (0..n-1)
    hwalls: list[list[bool]]
    rooms: list[tuple[int, int]]
    entry_row: int
    grid: ArenaGrid
    survivors: list[Survivor] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.spec.n

    def room_of(self, col: int, row: int) -> int | None:
        k = self.spec.room_cells
        for idx, (ri, rj) in enumerate(self.rooms):
            if ri <= col < ri + k and rj <= row < rj + k:
                return idx
        return None

    def open_neighbours(self, col: int, row: int) -> list[tuple[int, int]]:
        out = []
        if col > 0 and not self.vwalls[col][row]:
            out.append((col - 1, row))
        if col < self.n - 1 and not self.vwalls[col + 1][row]:
            out.append((col + 1, row))
        if row > 0 and not self.hwalls[col][row]:
            out.append((col, row - 1))
        if row < self.n - 1 and not self.hwalls[col][row + 1]:
            out.append((col, row + 1))
        return out

    def reachable_cells(self) -> set[tuple[int, int]]:
        start = (0, self.entry_row)
        seen = {start}
        stack = [start]
        while stack:
            for nb in self.open_neighbours(*stack.pop()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return seen


class _DisjointSet:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, a):
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[rb] = ra
        return True


def _place_rooms(spec: MazeSpec, rng: random.Random, entry_row: int) -> list[tuple[int, int]]:
    n, k = spec.n, spec.room_cells
    rooms: list[tuple[int, int]] = []

    def clashes(i: int, j: int) -> bool:
        if i == 0 and j <= entry_row < j + k:
            return True  # keep the entry cell a corridor
        # one-cell gap between rooms so each stays a distinct room
        return any(i < ri + k + 1 and ri < i + k + 1 and j < rj + k + 1 and rj < j + k + 1 for ri, rj in rooms)

    for _ in range(5000):
        if len(rooms) == spec.rooms:
            break
        i, j = rng.randint(0, n - k), rng.randint(0, n - k)
        if not clashes(i, j):
            rooms.append((i, j))
    if len(rooms) < spec.rooms:
        raise ValueError(f"could only fit {len(rooms)} of {spec.rooms} rooms; use fewer rooms or a larger arena")
    return rooms


def generate(spec: MazeSpec) -> Maze:
    spec.validate()
    rng = random.Random(spec.seed)
    n, k = spec.n, spec.room_cells
    vwalls = [[True] * n for _ in range(n + 1)]
    hwalls = [[True] * (n + 1) for _ in range(n)]
    entry_row = n // 2

    rooms = _place_rooms(spec, rng, entry_row)
    cells = [(i, j) for i in range(n) for j in range(n)]
    ds = _DisjointSet(cells)
    room_index = {}
    for idx, (ri, rj) in enumerate(rooms):
        for i in range(ri, ri + k):
            for j in range(rj, rj + k):
                room_index[(i, j)] = idx
                if i > ri:
                    vwalls[i][j] = False
                    ds.union((i - 1, j), (i, j))
                if j > rj:
                    hwalls[i][j] = False
                    ds.union((i, j - 1), (i, j))

    # Interior edges as (kind, line, along, cell_a, cell_b)
    edges = []
    for i in range(1, n):
        for j in range(n):
            edges.append(("v", i, j, (i - 1, j), (i, j)))
    for j in range(1, n):
        for i in range(n):
            edges.append(("h", j, i, (i, j - 1), (i, j)))
    rng.shuffle(edges)

    def remove(kind: str, line: int, along: int) -> None:
        if kind == "v":
            vwalls[line][along] = False
        else:
            hwalls[along][line] = False

    remaining = []
    for edge in edges:
        kind, line, along, a, b = edge
        if ds.union(a, b):
            remove(kind, line, along)
        else:
            remaining.append(edge)

    # Braid: extra openings for loops, but never extra doors into rooms.
    for kind, line, along, a, b in remaining:
        wall_present = vwalls[line][along] if kind == "v" else hwalls[along][line]
        is_room_boundary = room_index.get(a) != room_index.get(b)
        if wall_present and not is_room_boundary and rng.random() < spec.braid:
            remove(kind, line, along)

    vwalls[0][entry_row] = False  # entry / exit opening in the west wall

    grid = ArenaGrid(
        origin_x=spec.standoff_m,
        origin_y=-(entry_row + 0.5) * spec.cell_m,
        cell_m=spec.cell_m,
        cols=n,
        rows=n,
    )
    maze = Maze(spec=spec, vwalls=vwalls, hwalls=hwalls, rooms=rooms, entry_row=entry_row, grid=grid)
    maze.survivors = _place_survivors(maze, rng)
    return maze


def _place_survivors(maze: Maze, rng: random.Random) -> list[Survivor]:
    spec, k = maze.spec, maze.spec.room_cells
    blocks = [(ri, rj, k) for ri, rj in maze.rooms]
    rng.shuffle(blocks)
    if spec.survivors > len(blocks):
        dead_ends = [
            (i, j, 1)
            for i in range(maze.n)
            for j in range(maze.n)
            if maze.room_of(i, j) is None and len(maze.open_neighbours(i, j)) == 1 and (i, j) != (0, maze.entry_row)
        ]
        rng.shuffle(dead_ends)
        blocks += dead_ends
    if spec.survivors > len(blocks):
        raise ValueError(f"not enough rooms or dead ends for {spec.survivors} survivors")

    margin = min(0.35, spec.cell_m * 0.3)
    survivors = []
    for idx, (ci, cj, size) in enumerate(blocks[: spec.survivors], start=1):
        gx = rng.uniform(ci * spec.cell_m + margin, (ci + size) * spec.cell_m - margin)
        gy = rng.uniform(cj * spec.cell_m + margin, (cj + size) * spec.cell_m - margin)
        x, y = maze.grid.from_grid_frame(gx, gy)
        col, row = maze.grid.cell_of(x, y)
        survivors.append(
            Survivor(
                name=f"survivor_{idx}", x=round(x, 3), y=round(y, 3),
                yaw=round(rng.uniform(-math.pi, math.pi), 3), col=col, row=row, label=maze.grid.label(col, row),
            )
        )
    return survivors


def wall_segments(maze: Maze) -> list[tuple[float, float, float, float]]:
    """Merged wall boxes as (center_x, center_y, size_x, size_y) in the world frame."""
    spec, n, cell, t = maze.spec, maze.n, maze.spec.cell_m, maze.spec.wall_thickness_m
    ox, oy = maze.grid.origin_x, maze.grid.origin_y
    boxes = []
    for i in range(n + 1):
        j = 0
        while j < n:
            if maze.vwalls[i][j]:
                start = j
                while j < n and maze.vwalls[i][j]:
                    j += 1
                length = (j - start) * cell
                boxes.append((ox + i * cell, oy + (start * cell + j * cell) / 2, t, length + t))
            else:
                j += 1
    for j in range(n + 1):
        i = 0
        while i < n:
            if maze.hwalls[i][j]:
                start = i
                while i < n and maze.hwalls[i][j]:
                    i += 1
                length = (i - start) * cell
                boxes.append((ox + (start * cell + i * cell) / 2, oy + j * cell, length + t, t))
            else:
                i += 1
    return boxes


_WORLD_PLUGINS = """
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-air-pressure-system" name="gz::sim::systems::AirPressure"/>
    <plugin filename="gz-sim-air-speed-system" name="gz::sim::systems::AirSpeed"/>
    <plugin filename="gz-sim-altimeter-system" name="gz::sim::systems::Altimeter"/>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-magnetometer-system" name="gz::sim::systems::Magnetometer"/>
    <plugin filename="gz-sim-navsat-system" name="gz::sim::systems::NavSat"/>"""


def _box_link(name: str, cx: float, cy: float, cz: float, sx: float, sy: float, sz: float, rgba: str, collide: bool = True) -> str:
    geom = f"<geometry><box><size>{sx:.3f} {sy:.3f} {sz:.3f}</size></box></geometry>"
    collision = f"<collision name='c'>{geom}</collision>" if collide else ""
    return (
        f"<link name='{name}'><pose>{cx:.3f} {cy:.3f} {cz:.3f} 0 0 0</pose>{collision}"
        f"<visual name='v'>{geom}<material><ambient>{rgba}</ambient><diffuse>{rgba}</diffuse></material></visual></link>"
    )


def _offline_dummy(s: Survivor) -> str:
    """Simple lying mannequin made of primitives, for runs without internet access to Gazebo Fuel."""
    skin, cloth = "0.85 0.65 0.5 1", "0.2 0.3 0.6 1"
    parts = [
        _box_link("legs", -0.45, 0, 0.08, 0.9, 0.3, 0.15, cloth),
        _box_link("torso", 0.3, 0, 0.1, 0.6, 0.4, 0.2, cloth),
        _box_link("head", 0.72, 0, 0.1, 0.22, 0.18, 0.2, skin),
    ]
    return (
        f"<model name='{s.name}'><static>true</static><pose>{s.x} {s.y} 0 0 0 {s.yaw}</pose>{''.join(parts)}</model>"
    )


def to_sdf(maze: Maze, world_name: str, survivor_uri: str | None) -> str:
    spec = maze.spec
    h = spec.wall_height_m
    walls = "\n      ".join(
        _box_link(f"wall_{i}", cx, cy, h / 2, sx, sy, h, "0.75 0.75 0.72 1")
        for i, (cx, cy, sx, sy) in enumerate(wall_segments(maze))
    )
    if survivor_uri:
        survivors = "\n    ".join(
            f"<include><name>{s.name}</name><uri>{survivor_uri}</uri><static>true</static>"
            f"<pose>{s.x} {s.y} 0 0 0 {s.yaw}</pose></include>"
            for s in maze.survivors
        )
    else:
        survivors = "\n    ".join(_offline_dummy(s) for s in maze.survivors)
    launch_box = _box_link("launch_box", 0, 0, 0.001, 0.61, 0.61, 0.002, "0.9 0.35 0.05 1", collide=False)
    return f"""<?xml version="1.0" ?>
<!-- Generated by sim/maze_gen/navyam_maze.py (seed {spec.seed}). Do not edit by hand. -->
<sdf version="1.9">
  <world name="{world_name}">
    <physics name="1ms" type="ignore">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>{_WORLD_PLUGINS}
    <scene>
      <ambient>1.0 1.0 1.0</ambient>
      <background>0.8 0.8 0.8</background>
      <sky></sky>
    </scene>
    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.8 0.8 0.8 1</diffuse>
      <specular>0.8 0.8 0.8 1</specular>
      <direction>-0.5 0.1 -0.9</direction>
    </light>
    <spherical_coordinates>
      <latitude_deg>-35.3632621</latitude_deg>
      <longitude_deg>149.1652374</longitude_deg>
      <elevation>10.0</elevation>
      <heading_deg>0</heading_deg>
      <surface_model>EARTH_WGS84</surface_model>
    </spherical_coordinates>
    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="c"><geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry></collision>
        <visual name="v"><geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
          <material><ambient>0.5 0.5 0.5 1</ambient><diffuse>0.5 0.5 0.5 1</diffuse></material></visual>
      </link>
    </model>
    <model name="launch_area"><static>true</static>{launch_box}</model>
    <model name="arena">
      <static>true</static>
      {walls}
    </model>
    {survivors}
  </world>
</sdf>
"""


def to_yaml(maze: Maze, world_name: str) -> str:
    g, s = maze.grid, maze.spec
    lines = [
        "# Generated by sim/maze_gen/navyam_maze.py. Ground truth for scoring sim runs.",
        f"world_name: {world_name}",
        f"seed: {s.seed}",
        "arena:",
        f"  size_m: {s.arena_m}",
        f"  cell_m: {s.cell_m}",
        f"  cols: {g.cols}",
        f"  rows: {g.rows}",
        f"  origin_x: {g.origin_x}",
        f"  origin_y: {g.origin_y}",
        f"  yaw: {g.yaw}",
        f"  entry_row: {maze.entry_row}",
        f"  entry_label: {g.label(0, maze.entry_row)}",
        "rooms:",
    ]
    lines += [f"  - {{col: {i}, row: {j}, size_cells: {s.room_cells}}}" for i, j in maze.rooms]
    lines.append("survivors:")
    lines += [
        f"  - {{name: {v.name}, x: {v.x}, y: {v.y}, col: {v.col}, row: {v.row}, label: {v.label}}}"
        for v in maze.survivors
    ]
    return "\n".join(lines) + "\n"


def to_ros_params(maze: Maze) -> str:
    g = maze.grid
    return (
        "# Generated by sim/maze_gen/navyam_maze.py. Grid parameters for every navyam node.\n"
        "/**:\n"
        "  ros__parameters:\n"
        f"    grid_origin_x: {g.origin_x}\n"
        f"    grid_origin_y: {g.origin_y}\n"
        f"    grid_yaw: {g.yaw}\n"
        f"    grid_cell_m: {g.cell_m}\n"
        f"    grid_cols: {g.cols}\n"
        f"    grid_rows: {g.rows}\n"
        f"    expected_survivors: {len(maze.survivors)}\n"
    )


def to_ascii(maze: Maze) -> str:
    """Top view, north (+y) up. R = room cell, S = survivor, > = entry."""
    n = maze.n
    marks = {(v.col, v.row): "S" for v in maze.survivors}
    out = []
    for j in range(n - 1, -1, -1):
        out.append("+" + "".join("--+" if maze.hwalls[i][j + 1] else "  +" for i in range(n)))
        row = ""
        for i in range(n):
            left = "|" if maze.vwalls[i][j] else (">" if i == 0 and j == maze.entry_row else " ")
            fill = marks.get((i, j)) or ("R" if maze.room_of(i, j) is not None else " ")
            row += left + fill * 2
        row += "|" if maze.vwalls[n][j] else " "
        out.append(row)
    out.append("+" + "".join("--+" if maze.hwalls[i][0] else "  +" for i in range(n)))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", required=True, help="output path without extension, e.g. sim/worlds/nidar_s7")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--arena", type=float, default=15.0, help="arena side in metres (default 15)")
    p.add_argument("--cell", type=float, default=1.0, help="grid cell / corridor width in metres (default 1)")
    p.add_argument("--room", type=float, default=2.0, help="room side in metres (default 2)")
    p.add_argument("--rooms", type=int, default=6)
    p.add_argument("--survivors", type=int, default=6)
    p.add_argument("--braid", type=float, default=0.15, help="fraction of extra walls removed to create loops")
    p.add_argument("--survivor-uri", default=FUEL_SURVIVOR_URI, help="Gazebo model URI for survivors")
    p.add_argument("--offline", action="store_true", help="use built-in primitive dummies instead of Fuel models")
    p.add_argument("--ascii", action="store_true", help="print a top view")
    args = p.parse_args(argv)

    spec = MazeSpec(
        arena_m=args.arena, cell_m=args.cell, room_m=args.room, rooms=args.rooms,
        survivors=args.survivors, braid=args.braid, seed=args.seed,
    )
    try:
        maze = generate(spec)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    world_name = out.name
    uri = None if args.offline else args.survivor_uri
    out.with_suffix(".sdf").write_text(to_sdf(maze, world_name, uri), encoding="utf-8", newline="\n")
    out.with_suffix(".yaml").write_text(to_yaml(maze, world_name), encoding="utf-8", newline="\n")
    Path(f"{out}.params.yaml").write_text(to_ros_params(maze), encoding="utf-8", newline="\n")
    if args.ascii:
        print(to_ascii(maze))
    for s in maze.survivors:
        print(f"{s.name}: ({s.x:.2f}, {s.y:.2f}) cell {s.label}")
    print(f"wrote {out}.sdf, {out}.yaml, {out}.params.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
