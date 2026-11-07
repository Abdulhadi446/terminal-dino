#!/usr/bin/env python3
"""terminal-dino — Chrome's offline dino, resized for your terminal.

Zero dependencies: Python 3.8+, curses, and a terminal at least 40x18.
"""

from __future__ import annotations

import argparse
import curses
import locale
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- tuning
FPS = 30
FRAME_TIME = 1.0 / FPS
DINO_X = 7
DINO_W = 11
DINO_H = 9
JUMP_V = 42.0          # cells / second
GRAVITY = 88.0         # cells / second^2
FAST_FALL = 70.0       # extra gravity while holding down mid-air
BASE_SPEED = 30.0      # cells / second
MAX_SPEED = 65.0
SPEED_PER_POINT = 0.0045
SCORE_PER_CELL = 0.45
DUCK_TIME = 1.2        # seconds a tap of down keeps you ducking
NIGHT_EVERY = 500      # score between day/night flips

# ---------------------------------------------------------------- sprites
DINO_RUN = [
    [
        "    █████  ",
        "   ███████ ",
        "   ███ ███ ",
        "   ███████ ",
        "   ██████  ",
        "█  █████   ",
        "██ ██████  ",
        "█████████  ",
        "  ███ ███  ",
    ],
    [
        "    █████  ",
        "   ███████ ",
        "   ███ ███ ",
        "   ███████ ",
        "   ██████  ",
        "█  █████   ",
        "██ ██████  ",
        "█████████  ",
        "  ██   ███ ",
    ],
]
DINO_JUMP = [
    "    █████  ",
    "   ███████ ",
    "   ███ ███ ",
    "   ███████ ",
    "   ██████  ",
    "█  █████   ",
    "██ ██████  ",
    "█████████  ",
    "   ██  ███ ",
]
DINO_DEAD = [
    "    █████  ",
    "   ███████ ",
    "   ███x███ ",
    "   ███████ ",
    "   ██████  ",
    "█  █████   ",
    "██ ██████  ",
    "█████████  ",
    "  ███ ███  ",
]
DINO_DUCK = [
    [
        "██    ██████ ",
        "███  ████████",
        "█████████████",
        "  ███  ███   ",
    ],
    [
        "██    ██████ ",
        "███  ████████",
        "█████████████",
        "  ██   ███   ",
    ],
]
CACTUS_SMALL = [
    " █ ",
    "███",
    " █ ",
    " █ ",
]
CACTUS_LARGE = [
    "  ██ ",
    "  ██ ",
    "█ ██ ",
    "███ █",
    "  ███",
    "  ██ ",
]
BIRD = [
    [
        "     ███  ",
        "    █████ ",
        "██ ███████",
        " ███  ███ ",
    ],
    [
        "██        ",
        "██████    ",
        " █████████",
        "   ███ ██ ",
    ],
]
CLOUD = [
    "   ███   ",
    " ███████ ",
]
MOON = [
    "  ██  ",
    " ████ ",
    "███   ",
    " ████ ",
]
FONT = {
    "D": ["████ ", "█   █", "█   █", "█   █", "████ "],
    "I": ["█████", "  █  ", "  █  ", "  █  ", "█████"],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "O": [" ███ ", "█   █", "█   █", "█   █", " ███ "],
}
TITLE = "DINO"


# ---------------------------------------------------------------- helpers
def art_width(rows: list[str]) -> int:
    return max(len(r) for r in rows)


def column_runs(rows: list[str]) -> list[tuple[int, int]]:
    """Inclusive runs of columns that contain at least one solid pixel."""
    w = art_width(rows)
    occupied = [any(i < len(r) and r[i] != " " for r in rows) for i in range(w)]
    runs: list[tuple[int, int]] = []
    start = None
    for i, solid in enumerate(occupied + [False]):
        if solid and start is None:
            start = i
        elif not solid and start is not None:
            runs.append((start, i - 1))
            start = None
    return runs


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "terminal-dino"


def load_high() -> int:
    try:
        return int((data_dir() / "highscore").read_text().strip())
    except (OSError, ValueError):
        return 0


def save_high(score: int) -> None:
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "highscore").write_text(str(score))
    except OSError:
        pass


@dataclass
class Obstacle:
    kind: str                 # cactus | bird_low | bird_high
    x: float
    y: int                    # top row on screen
    rows: list[str]
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    passed: bool = False

    @property
    def width(self) -> int:
        return art_width(self.rows)


@dataclass
class Cloud:
    x: float
    y: int
    speed_scale: float = 0.18


# ---------------------------------------------------------------- game state
class Game:
    def __init__(self, demo: bool = False) -> None:
        self.demo = demo
        self.high = load_high()
        self.state = "title"
        self.quit = False
        self.w = 80
        self.h = 24
        self.ground = 21
        self.t = 0.0
        self.ground_offset = 0.0
        self.clouds: list[Cloud] = []
        self.stars: list[tuple[int, int, str, float]] = []
        self.night = False
        self.new_best = False
        self.reset()
        self._seed_clouds()

    # ---------------------------------------------------------- lifecycle
    def reset(self) -> None:
        self.distance = 0.0
        self.score = 0
        self.speed = BASE_SPEED
        self.jump_h = 0.0
        self.jump_v = 0.0
        self.on_ground = True
        self.duck_timer = 0.0
        self.jump_buffer = 0.0
        self.obstacles: list[Obstacle] = []
        self.next_spawn = 55.0
        self.run_anim = 0.0
        self.flash = 0.0
        self.dead_timer = 0.0
        self.night = False
        self.next_night = NIGHT_EVERY
        self.stars = []
        self.new_best = False

    def start(self) -> None:
        self.reset()
        self.state = "play"

    def _seed_clouds(self) -> None:
        self.clouds = [
            Cloud(x=random.uniform(0, 80), y=random.randint(3, 9), speed_scale=random.uniform(0.12, 0.24))
            for _ in range(4)
        ]

    def resize(self, w: int, h: int) -> None:
        self.w = w
        self.h = h
        self.ground = max(8, h - 3)
        for c in self.clouds:
            if c.x > w:
                c.x = random.uniform(0, w)
            if c.y >= self.ground - 8:
                c.y = random.randint(2, max(3, self.ground - 9))

    # ---------------------------------------------------------- input
    def handle_key(self, ch: int) -> None:
        if ch in (-1, curses.KEY_RESIZE):
            return
        if ch in (ord("q"), ord("Q"), 27):
            self.quit = True
            return

        if self.state == "title":
            if ch in (ord(" "), 10, 13, curses.KEY_UP, ord("w"), ord("W")):
                self.start()
            elif self.demo:
                self.start()
            return

        if self.state == "dead":
            if self.dead_timer > 0:
                return
            if ch in (ord(" "), 10, 13, ord("r"), ord("R"), curses.KEY_UP):
                self.start()
            return

        if self.state == "paused":
            if ch in (ord("p"), ord("P"), ord(" ")):
                self.state = "play"
            return

        # playing
        if ch in (ord("p"), ord("P")):
            self.state = "paused"
        elif ch in (ord(" "), 10, 13, curses.KEY_UP, ord("w"), ord("W")):
            self.jump()
        elif ch in (curses.KEY_DOWN, ord("s"), ord("S")):
            self.duck_timer = DUCK_TIME
            if not self.on_ground:
                self.jump_v -= 12.0     # a small shove downwards

    def jump(self) -> None:
        if self.on_ground:
            self.on_ground = False
            self.jump_v = JUMP_V
            self.jump_h = 0.0
            self.duck_timer = 0.0
        elif self.jump_h < 1.0:
            self.jump_buffer = 0.12

    # ---------------------------------------------------------- update
    def update(self, dt: float) -> None:
        dt = min(dt, 0.05)
        self.t += dt

        if self.state == "title":
            self.ground_offset += BASE_SPEED * 0.45 * dt
            self._update_clouds(dt, 0.25)
            return

        if self.state == "dead":
            self.dead_timer = max(0.0, self.dead_timer - dt)
            self._update_clouds(dt, 0.1)
            return
        if self.state == "paused":
            return

        # ---- play
        self.speed = min(MAX_SPEED, BASE_SPEED + self.score * SPEED_PER_POINT)
        self.distance += self.speed * dt
        old_score = self.score
        self.score = int(self.distance * SCORE_PER_CELL)
        if self.score // 100 > old_score // 100:
            self.flash = 0.55
        if self.score >= self.next_night:
            self.night = not self.night
            self.next_night += NIGHT_EVERY
            self.stars = self._make_stars() if self.night else []
        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt)

        self.run_anim += dt
        self.ground_offset += self.speed * dt
        self._update_clouds(dt, 0.65)

        if self.duck_timer > 0:
            self.duck_timer = max(0.0, self.duck_timer - dt)
        if self.jump_buffer > 0:
            self.jump_buffer = max(0.0, self.jump_buffer - dt)

        if not self.on_ground:
            g = GRAVITY + (FAST_FALL if self.duck_timer > 0 else 0.0)
            self.jump_v -= g * dt
            self.jump_h += self.jump_v * dt
            if self.jump_h <= 0:
                self.jump_h = 0.0
                self.jump_v = 0.0
                self.on_ground = True
                if self.jump_buffer > 0:
                    self.jump_buffer = 0.0
                    self.jump()

        # spawn + move obstacles
        self.next_spawn -= self.speed * dt
        if self.next_spawn <= 0:
            self.spawn_obstacle()
            gap = self.speed * random.uniform(1.0, 1.5)
            self.next_spawn = max(30.0, gap)

        for ob in self.obstacles:
            ob.x -= self.speed * dt
        self.obstacles = [o for o in self.obstacles if o.x + o.width > -2]

        if self.demo:
            self._autopilot()

        if self._collides():
            self.die()

    def die(self) -> None:
        self.state = "dead"
        self.dead_timer = 0.55
        if self.score > self.high:
            self.high = self.score
            self.new_best = True
            if not self.demo:
                save_high(self.high)

    def _update_clouds(self, dt: float, factor: float) -> None:
        for c in self.clouds:
            c.x -= self.speed * c.speed_scale * factor * dt
            if c.x < -10:
                c.x = self.w + random.uniform(0, 30)
                c.y = random.randint(2, max(3, self.ground - 10))

    def _make_stars(self) -> list[tuple[int, int, str, float]]:
        count = max(6, self.w // 6)
        return [
            (
                random.randint(1, max(2, self.w - 2)),
                random.randint(1, max(2, self.ground - 10)),
                random.choice("·.*+✦"),
                random.uniform(0, math.tau),
            )
            for _ in range(count)
        ]

    # ---------------------------------------------------------- spawning
    def spawn_obstacle(self) -> None:
        x = self.w + 2.0
        h = len(CACTUS_SMALL)
        if self.score > 200 and random.random() < 0.28:
            high = random.random() < 0.45
            rows = random.choice(BIRD)
            y = self.ground - 11 if high else self.ground - 5
            boxes = [(2, 1, 8, 3)]
            self.obstacles.append(Obstacle("bird_high" if high else "bird_low", x, y, rows, boxes))
            return

        large = self.score > 60 and random.random() < 0.45
        art = CACTUS_LARGE if large else CACTUS_SMALL
        if large:
            count = 1 if self.score < 800 else random.choice([1, 1, 2])
        elif self.score < 1300:
            count = random.choice([1, 1, 2])
        else:
            count = random.choices([1, 2, 3], weights=[4, 4, 2])[0]
        rows = [""] * len(art)
        for _ in range(count):
            w = art_width(art)
            for i, row in enumerate(art):
                rows[i] += row.ljust(w)
        boxes: list[tuple[int, int, int, int]] = []
        for a, b in column_runs(rows):
            boxes.append((a, 0, b, len(rows) - 1))
        y = self.ground - len(rows)
        self.obstacles.append(Obstacle("cactus", x, y, rows, boxes))

    # ---------------------------------------------------------- collision
    def _dino_boxes(self) -> list[tuple[float, float, float, float]]:
        top = self.ground - DINO_H - self.jump_h
        if self.on_ground and self.duck_timer > 0:
            return [(DINO_X + 2, self.ground - 3, DINO_X + 11, self.ground - 2)]
        return [(DINO_X + 2, top + 1, DINO_X + 9, top + DINO_H - 1)]

    def _collides(self) -> bool:
        dino = self._dino_boxes()
        for ob in self.obstacles:
            for bx1, by1, bx2, by2 in ob.boxes:
                ox1, oy1 = ob.x + bx1, ob.y + by1
                ox2, oy2 = ob.x + bx2, ob.y + by2
                for dx1, dy1, dx2, dy2 in dino:
                    if dx1 <= ox2 and ox1 <= dx2 and dy1 <= oy2 and oy1 <= dy2:
                        return True
        return False

    # ---------------------------------------------------------- demo
    def _autopilot(self) -> None:
        if self.duck_timer > 0.08:
            return
        dino_right = DINO_X + 9
        upcoming = [o for o in self.obstacles if o.x + o.width > DINO_X]
        if not upcoming:
            return
        ob = min(upcoming, key=lambda o: o.x)
        lead = (ob.x - dino_right) / max(self.speed, 1.0)
        if ob.kind == "bird_high":
            if -0.05 < lead < 0.50:
                self.duck_timer = 1.3
        elif ob.kind in ("cactus", "bird_low"):
            if -0.05 < lead < 0.30 and self.on_ground:
                self.jump()


# ---------------------------------------------------------------- drawing
def safe_addstr(win, y: int, x: int, text: str, attr: int = 0) -> None:
    h, w = win.getmaxyx()
    if not text or y < 0 or y >= h:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    if x >= w or not text:
        return
    try:
        win.addstr(y, x, text[: w - x], attr)
    except curses.error:
        pass


def draw_art(win, y: int, x: int, rows: list[str], attr: int) -> None:
    for i, row in enumerate(rows):
        safe_addstr(win, y + i, x, row, attr)


def draw_center(win, y: int, text: str, attr: int = 0) -> None:
    w = win.getmaxyx()[1]
    safe_addstr(win, y, max(0, (w - len(text)) // 2), text, attr)


def clear_band(win, y: int, text: str, pad: int = 1) -> None:
    """Erase anything behind a centered line (clouds, mostly)."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h:
        return
    x = max(0, (w - len(text)) // 2 - pad)
    safe_addstr(win, y, x, " " * min(w - x, len(text) + pad * 2), 0)


def clear_rect(win, y: int, x: int, width: int, height: int) -> None:
    h, w = win.getmaxyx()
    x = max(0, x)
    width = min(width, w - x)
    for row in range(y, y + height):
        if 0 <= row < h and width > 0:
            safe_addstr(win, row, x, " " * width, 0)


def init_colors() -> bool:
    try:
        if not curses.has_colors():
            return False
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_WHITE, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_BLUE, -1)
        return True
    except curses.error:
        return False


def make_palette(game: Game) -> dict[str, int]:
    has = getattr(game, "color", False)
    yellow = (curses.color_pair(3) | curses.A_BOLD) if has else curses.A_BOLD
    if game.night:
        main = (curses.color_pair(4) | curses.A_BOLD) if has else curses.A_BOLD
        ground = (curses.color_pair(5) | curses.A_DIM) if has else curses.A_DIM
        cloud = (curses.color_pair(4) | curses.A_DIM) if has else curses.A_DIM
    else:
        main = (curses.color_pair(1) | curses.A_BOLD) if has else curses.A_BOLD
        ground = (curses.color_pair(1) | curses.A_DIM) if has else curses.A_DIM
        cloud = (curses.color_pair(2) | curses.A_DIM) if has else curses.A_DIM
    return {"main": main, "ground": ground, "cloud": cloud, "score": yellow}


def draw_ground(win, game: Game, pal: dict[str, int]) -> None:
    safe_addstr(win, game.ground, 0, "─" * game.w, pal["ground"])
    pattern = "  ·    '   .     ,    ·  '    .  "
    off = int(game.ground_offset) % len(pattern)
    row = "".join(pattern[(x + off) % len(pattern)] for x in range(game.w))
    if game.ground + 1 < game.h:
        safe_addstr(win, game.ground + 1, 0, row, pal["ground"])


def draw_clouds(win, game: Game, pal: dict[str, int]) -> None:
    for c in game.clouds:
        draw_art(win, c.y, int(c.x), CLOUD, pal["cloud"])


def draw_sky(win, game: Game, pal: dict[str, int]) -> None:
    if not game.night:
        return
    for x, y, ch, phase in game.stars:
        bright = math.sin(game.t * 1.8 + phase)
        safe_addstr(win, y, x, ch, pal["score"] if bright > 0.35 else pal["cloud"])
    if game.w >= 60:
        draw_art(win, 2, game.w - 10, MOON, pal["score"])


def draw_hud(win, game: Game, pal: dict[str, int], show_score: bool = True) -> None:
    high = f"HI {game.high:05d}"
    score = f"{game.score:05d}"
    right = (len(high) + len(score) + 2) if show_score else len(high)
    x = game.w - right
    if x < 0:
        return
    safe_addstr(win, 0, x, high, pal["cloud"])
    if not show_score:
        return
    attr = pal["score"]
    if game.flash > 0 and int(game.flash * 18) % 2 == 0:
        attr |= curses.A_REVERSE
    safe_addstr(win, 0, x + len(high) + 2, score, attr)


def draw_dino(win, game: Game, pal: dict[str, int]) -> None:
    if game.state == "dead":
        draw_art(win, game.ground - DINO_H, DINO_X, DINO_DEAD, pal["main"])
        return
    if game.on_ground and game.duck_timer > 0:
        y = game.ground - 4
        frame = DINO_DUCK[int(game.run_anim * 8) % 2]
    elif not game.on_ground:
        y = round(game.ground - DINO_H - game.jump_h)
        frame = DINO_JUMP
    else:
        y = game.ground - DINO_H
        frame = DINO_RUN[int(game.run_anim * 9) % 2]
    draw_art(win, y, DINO_X, frame, pal["main"])


def draw_obstacles(win, game: Game, pal: dict[str, int]) -> None:
    for ob in game.obstacles:
        rows = BIRD[int(game.t * 10) % 2] if ob.kind.startswith("bird") else ob.rows
        draw_art(win, ob.y, int(round(ob.x)), rows, pal["main"])


def draw_playfield(win, game: Game, pal: dict[str, int]) -> None:
    draw_sky(win, game, pal)
    draw_clouds(win, game, pal)
    draw_ground(win, game, pal)
    draw_obstacles(win, game, pal)
    draw_dino(win, game, pal)
    draw_hud(win, game, pal)


def logo_lines() -> list[str]:
    rows = [""] * 5
    for ch in TITLE:
        glyph = FONT[ch]
        for i in range(5):
            rows[i] += glyph[i] + " "
    return [r.rstrip() for r in rows]


def draw_title(win, game: Game, pal: dict[str, int]) -> None:
    y0 = max(3, game.ground - 17)
    lines = logo_lines()
    logo_w = max(len(line) for line in lines)
    for i in range(len(lines)):
        clear_band(win, y0 + i, "x" * logo_w, pad=2)
    for i, line in enumerate(lines):
        draw_center(win, y0 + i, line, pal["main"])
    clear_band(win, y0 + 7, "the chrome dino, in your terminal", pad=2)
    draw_center(win, y0 + 7, "the chrome dino, in your terminal", pal["cloud"])
    if int(game.t * 1.6) % 2 == 0:
        clear_band(win, y0 + 9, "press SPACE to start", pad=2)
        draw_center(win, y0 + 9, "press SPACE to start", pal["score"] | curses.A_BOLD)
    if y0 >= 3:
        clear_band(win, y0 - 2, "T E R M I N A L", pad=2)
        draw_center(win, y0 - 2, "T E R M I N A L", pal["cloud"])
    for cx, art in ((game.w // 5, CACTUS_LARGE), (game.w * 3 // 5, CACTUS_SMALL)):
        draw_art(win, game.ground - len(art), cx, art, pal["main"])
    if game.w >= 62 and game.h >= 22:
        x = game.w - 22
        frame = DINO_RUN[int(game.t * 7) % 2]
        draw_art(win, game.ground - DINO_H, x, frame, pal["main"])
    draw_ground(win, game, pal)
    controls = "SPACE/↑ jump   ↓ duck   P pause   Q quit"
    draw_center(win, game.h - 1, controls, pal["cloud"])
    draw_hud(win, game, pal, show_score=False)


def draw_dead_overlay(win, game: Game, pal: dict[str, int]) -> None:
    cy = max(2, game.ground - 18)
    w = win.getmaxyx()[1]
    panel_w = min(w, 56)
    clear_rect(win, max(0, cy - 1), (w - panel_w) // 2, panel_w, 7)
    draw_center(win, cy, "G A M E   O V E R", pal["score"] | curses.A_BOLD)
    draw_center(win, cy + 2, f"score {game.score:05d}    best {game.high:05d}", pal["main"])
    if game.new_best:
        draw_center(win, cy + 3, "★ NEW BEST ★", pal["score"] | curses.A_BOLD)
    if game.dead_timer <= 0 and int(game.t * 1.8) % 2 == 0:
        draw_center(win, cy + 5, "press SPACE to run again", pal["cloud"] | curses.A_BOLD)


def draw_pause_overlay(win, game: Game, pal: dict[str, int]) -> None:
    cy = max(2, game.ground - 18)
    w = win.getmaxyx()[1]
    panel_w = min(w, 40)
    clear_rect(win, max(0, cy - 1), (w - panel_w) // 2, panel_w, 5)
    draw_center(win, cy, "P A U S E D", pal["score"] | curses.A_BOLD)
    draw_center(win, cy + 2, "press P to resume", pal["cloud"])


def draw_too_small(win) -> None:
    h, w = win.getmaxyx()
    draw_center(win, h // 2 - 1, "terminal too small", curses.A_BOLD)
    draw_center(win, h // 2 + 1, f"need 40x18 (now {w}x{h})", curses.A_DIM)


def draw(win, game: Game) -> None:
    win.erase()
    h, w = win.getmaxyx()
    if w < 40 or h < 18:
        draw_too_small(win)
        win.refresh()
        return
    pal = make_palette(game)
    if game.state == "title":
        draw_title(win, game, pal)
    else:
        draw_playfield(win, game, pal)
        if game.state == "dead":
            draw_dead_overlay(win, game, pal)
        elif game.state == "paused":
            draw_pause_overlay(win, game, pal)
    win.refresh()


# ---------------------------------------------------------------- main loop
def run(stdscr, demo: bool = False) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.keypad(True)
    game = Game(demo=demo)
    game.color = init_colors()
    h, w = stdscr.getmaxyx()
    game.resize(w, h)
    if demo:
        game.start()

    last = time.monotonic()
    while not game.quit:
        frame_start = time.monotonic()
        dt = frame_start - last
        last = frame_start

        while True:
            ch = stdscr.getch()
            if ch == -1:
                break
            game.handle_key(ch)

        h, w = stdscr.getmaxyx()
        if (w, h) != (game.w, game.h):
            game.resize(w, h)
        game.update(dt)
        if demo and game.state == "dead" and game.dead_timer <= 0:
            game.start()
        draw(stdscr, game)

        elapsed = time.monotonic() - frame_start
        if elapsed < FRAME_TIME:
            time.sleep(FRAME_TIME - elapsed)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="dino",
        description="Chrome's offline dino, running in your terminal.",
    )
    parser.add_argument("--demo", action="store_true", help="autopilot demo mode (for GIFs)")
    parser.add_argument("--reset-best", action="store_true", help="clear the saved high score")
    args = parser.parse_args(argv)

    if args.reset_best:
        save_high(0)
        print("high score cleared")
        return 0
    if not sys.stdout.isatty():
        print("terminal-dino needs an interactive terminal.")
        return 1

    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(run, args.demo)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

