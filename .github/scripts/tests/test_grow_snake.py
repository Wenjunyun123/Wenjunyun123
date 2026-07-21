import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grow_snake import (  # noqa: E402
    ContributionEvent,
    build_growth_timeline,
    inject_growth_animation,
    parse_contribution_events,
)


SAMPLE_SVG = """<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg"><style>
.s{animation:none linear 10000ms infinite}
@keyframes c0{10%{fill:red}10.1%,100%{fill:white}}
@keyframes c1{20%{fill:red}20.1%,100%{fill:white}}
</style>
<rect class="c c0" x="2" y="2" rx="2" ry="2"/>
<rect class="c c1" x="18" y="50" rx="2" ry="2"/>
<rect class="s s0" x="0.8" y="0.8" width="14.4" height="14.4" rx="4.5" ry="4.5"/>
</svg>"""


class GrowthTimelineTests(unittest.TestCase):
    def test_growth_is_linear_by_contribution_count(self):
        events = [
            ContributionEvent(10.0, 2, 0, 0),
            ContributionEvent(20.0, 6, 1, 3),
        ]
        key_times, scales = build_growth_timeline(events, max_scale=1.8)

        self.assertEqual(key_times, [0.0, 0.1, 0.2, 1.0])
        self.assertAlmostEqual(scales[1], 1.2)
        self.assertAlmostEqual(scales[2], 1.8)
        self.assertAlmostEqual(
            (scales[1] - 1.0) / 2,
            (scales[2] - scales[1]) / 6,
        )

    def test_svg_cells_map_to_exact_calendar_counts(self):
        events = parse_contribution_events(SAMPLE_SVG, {(0, 0): 2, (1, 3): 6})

        self.assertEqual([event.contribution_count for event in events], [2, 6])
        self.assertEqual([event.time_percent for event in events], [10.0, 20.0])

    def test_current_day_can_shift_to_one_adjacent_calendar_cell(self):
        events = parse_contribution_events(SAMPLE_SVG, {(0, 0): 2, (1, 4): 6})

        self.assertEqual([event.contribution_count for event in events], [2, 6])

    def test_growth_animation_is_injected_into_snake_rect(self):
        events = parse_contribution_events(SAMPLE_SVG, {(0, 0): 2, (1, 3): 6})
        output = inject_growth_animation(SAMPLE_SVG, events, max_scale=1.8)

        self.assertIn('data-growth="linear-by-contribution-count"', output)
        self.assertIn('data-total-contributions="8"', output)
        self.assertIn('attributeName="width"', output)
        self.assertIn('values="14.4;17.28;25.92;25.92"', output)
        self.assertIn('calcMode="discrete"', output)


if __name__ == "__main__":
    unittest.main()
