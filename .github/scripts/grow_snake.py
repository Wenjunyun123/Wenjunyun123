#!/usr/bin/env python3
"""Make a Platane/snk SVG grow from the real contribution counts it eats."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CELL_SIZE = 16.0
CELL_OFFSET = 2.0
CELL_RE = re.compile(
    r'<rect class="c c(?P<id>[0-9a-z]+)" '
    r'x="(?P<x>[\d.]+)" y="(?P<y>[\d.]+)"'
)
FRAME_RE = re.compile(r"@keyframes c(?P<id>[^\{]+)\{(?P<time>[\d.]+)%")
SNAKE_RECT_RE = re.compile(r'<rect class="s s[^"]+" [^>]*/>')
ATTRIBUTE_RE = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass(frozen=True)
class ContributionEvent:
    time_percent: float
    contribution_count: int
    week_index: int
    weekday: int


@dataclass(frozen=True)
class SnakeCell:
    cell_id: str
    time_percent: float
    week_index: int
    weekday: int


def fetch_contribution_counts(user: str, token: str) -> dict[tuple[int, int], int]:
    query = """
      query($login: String!) {
        user(login: $login) {
          contributionsCollection {
            contributionCalendar {
              weeks {
                contributionDays {
                  weekday
                  contributionCount
                }
              }
            }
          }
        }
      }
    """
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": user}}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "contribution-snake-growth",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL failed: {payload['errors']}")

    weeks = payload["data"]["user"]["contributionsCollection"][
        "contributionCalendar"
    ]["weeks"]
    return {
        (week_index, int(day["weekday"])): int(day["contributionCount"])
        for week_index, week in enumerate(weeks)
        for day in week["contributionDays"]
    }


def _cell_index(coordinate: float) -> int:
    raw_index = (coordinate - CELL_OFFSET) / CELL_SIZE
    index = round(raw_index)
    if abs(raw_index - index) > 0.01:
        raise ValueError(f"Unexpected contribution cell coordinate: {coordinate}")
    return index


def parse_contribution_events(
    svg: str, contribution_counts: dict[tuple[int, int], int]
) -> list[ContributionEvent]:
    frame_times = {
        match.group("id"): float(match.group("time"))
        for match in FRAME_RE.finditer(svg)
    }
    cells: list[SnakeCell] = []

    for match in CELL_RE.finditer(svg):
        cell_id = match.group("id")
        if cell_id not in frame_times:
            raise ValueError(f"Missing eat keyframe for contribution cell {cell_id}")

        week_index = _cell_index(float(match.group("x")))
        weekday = _cell_index(float(match.group("y")))
        cells.append(
            SnakeCell(
                cell_id=cell_id,
                time_percent=frame_times[cell_id],
                week_index=week_index,
                weekday=weekday,
            )
        )

    if not cells:
        raise ValueError("No animated contribution cells found in the snake SVG")

    # GitHub can move the current day's contributions by one cell when the SVG
    # generation and GraphQL query straddle a timezone/day boundary. Match every
    # exact positive cell first, then allow only an unused adjacent-day fallback.
    assignments: dict[SnakeCell, int] = {}
    used_positions: set[tuple[int, int]] = set()
    unmatched_cells: list[SnakeCell] = []
    for cell in cells:
        position = (cell.week_index, cell.weekday)
        count = contribution_counts.get(position, 0)
        if count > 0:
            assignments[cell] = count
            used_positions.add(position)
        else:
            unmatched_cells.append(cell)

    positive_candidates = {
        position: count
        for position, count in contribution_counts.items()
        if count > 0 and position not in used_positions
    }
    for cell in unmatched_cells:
        flat_cell = cell.week_index * 7 + cell.weekday
        nearby = sorted(
            (
                (abs((position[0] * 7 + position[1]) - flat_cell), position, count)
                for position, count in positive_candidates.items()
                if abs((position[0] * 7 + position[1]) - flat_cell) <= 1
            ),
            key=lambda item: item[0],
        )
        if not nearby or (len(nearby) > 1 and nearby[0][0] == nearby[1][0]):
            raise ValueError(
                "Animated contribution cell has no unambiguous contribution count: "
                f"week={cell.week_index}, weekday={cell.weekday}"
            )

        _, position, count = nearby[0]
        assignments[cell] = count
        del positive_candidates[position]

    events = [
        ContributionEvent(
            time_percent=cell.time_percent,
            contribution_count=assignments[cell],
            week_index=cell.week_index,
            weekday=cell.weekday,
        )
        for cell in cells
    ]
    return sorted(events, key=lambda event: event.time_percent)


def build_growth_timeline(
    events: Iterable[ContributionEvent], max_scale: float
) -> tuple[list[float], list[float]]:
    ordered = list(events)
    if max_scale <= 1.0:
        raise ValueError("max_scale must be greater than 1")

    total = sum(event.contribution_count for event in ordered)
    if total <= 0:
        raise ValueError("Total contribution count must be positive")

    key_times = [0.0]
    scales = [1.0]
    cumulative = 0
    for event in ordered:
        cumulative += event.contribution_count
        key_times.append(event.time_percent / 100.0)
        scales.append(1.0 + (max_scale - 1.0) * cumulative / total)

    if key_times[-1] < 1.0:
        key_times.append(1.0)
        scales.append(scales[-1])

    return key_times, scales


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _animation(attribute: str, values: list[float], key_times: list[float], duration: str) -> str:
    return (
        f'<animate attributeName="{attribute}" '
        f'values="{";".join(_number(value) for value in values)}" '
        f'keyTimes="{";".join(_number(value) for value in key_times)}" '
        f'dur="{duration}" calcMode="discrete" repeatCount="indefinite"/>'
    )


def inject_growth_animation(
    svg: str,
    events: list[ContributionEvent],
    max_scale: float,
) -> str:
    key_times, scales = build_growth_timeline(events, max_scale)
    duration_match = re.search(r"animation:none linear (\d+ms) infinite", svg)
    if not duration_match:
        raise ValueError("Could not find the snake animation duration")
    duration = duration_match.group(1)

    def replace_snake_rect(match: re.Match[str]) -> str:
        tag = match.group(0)
        attributes = dict(ATTRIBUTE_RE.findall(tag))
        required = ("x", "y", "width", "height", "rx", "ry")
        if any(name not in attributes for name in required):
            raise ValueError(f"Snake rectangle is missing geometry: {tag}")

        x = float(attributes["x"])
        y = float(attributes["y"])
        width = float(attributes["width"])
        height = float(attributes["height"])
        rx = float(attributes["rx"])
        ry = float(attributes["ry"])
        center_x = x + width / 2.0
        center_y = y + height / 2.0

        animated_values = {
            "x": [center_x - width * scale / 2.0 for scale in scales],
            "y": [center_y - height * scale / 2.0 for scale in scales],
            "width": [width * scale for scale in scales],
            "height": [height * scale for scale in scales],
            "rx": [rx * scale for scale in scales],
            "ry": [ry * scale for scale in scales],
        }
        animations = "".join(
            _animation(name, values, key_times, duration)
            for name, values in animated_values.items()
        )
        return (
            tag[:-2]
            + ' data-growth-mapping="linear-by-contribution-count">'
            + animations
            + "</rect>"
        )

    transformed, snake_rect_count = SNAKE_RECT_RE.subn(replace_snake_rect, svg)
    if snake_rect_count == 0:
        raise ValueError("No snake rectangles found in the SVG")

    total = sum(event.contribution_count for event in events)
    transformed = transformed.replace(
        "<svg ",
        (
            '<svg data-growth="linear-by-contribution-count" '
            f'data-total-contributions="{total}" '
            f'data-max-scale="{_number(max_scale)}" '
        ),
        1,
    )
    return transformed


def process_svg(
    path: Path,
    contribution_counts: dict[tuple[int, int], int],
    max_scale: float,
) -> tuple[int, int]:
    svg = path.read_text(encoding="utf-8")
    events = parse_contribution_events(svg, contribution_counts)
    transformed = inject_growth_animation(svg, events, max_scale)
    path.write_text(transformed, encoding="utf-8")
    return len(events), sum(event.contribution_count for event in events)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--max-scale", type=float, default=1.65)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    counts = fetch_contribution_counts(args.user, token)
    for path in args.paths:
        event_count, total = process_svg(path, counts, args.max_scale)
        print(
            f"Enhanced {path}: {event_count} contribution days, "
            f"{total} contributions, max scale {args.max_scale}x"
        )


if __name__ == "__main__":
    main()
