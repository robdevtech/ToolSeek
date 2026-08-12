# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offline unit checks for freecad.ToolSeek.matcher (no FreeCAD runtime required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# indexer imports FreeCADGui at module load; stub before package import.
sys.modules.setdefault("FreeCADGui", MagicMock())
sys.modules.setdefault("FreeCAD", MagicMock())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from freecad.ToolSeek.indexer import CommandInfo, _humanize_command_name  # noqa: E402
from freecad.ToolSeek.matcher import filter_commands, score  # noqa: E402


def _cmd(
    name: str,
    menu_text: str,
    *,
    active: bool = True,
    workbench_id: str = "",
    workbench_name: str = "",
    current_workbench: bool = False,
) -> CommandInfo:
    return CommandInfo(
        name=name,
        menu_text=menu_text,
        tooltip="",
        shortcut="",
        active=active,
        icon=None,
        workbench_id=workbench_id,
        workbench_name=workbench_name,
        current_workbench=current_workbench,
    )


class MatcherRankingTests(unittest.TestCase):
    def test_line_prefers_current_workbench_label(self):
        sketcher = _cmd(
            "Sketcher_CreateLine",
            "Create line",
            workbench_id="SketcherWorkbench",
            workbench_name="Sketcher",
            current_workbench=True,
        )
        draft = _cmd(
            "Draft_Line",
            "Line",
            workbench_id="DraftWorkbench",
            workbench_name="Draft",
            current_workbench=False,
        )
        part = _cmd(
            "Part_Line",
            "Line",
            workbench_id="PartWorkbench",
            workbench_name="Part",
            current_workbench=False,
        )
        ranked = filter_commands("line", [draft, part, sketcher])
        self.assertEqual(ranked[0].name, "Sketcher_CreateLine")
        self.assertLess(score("line", sketcher), score("line", draft))

    def test_line_create_beats_bspline_substring(self):
        """'line' must rank Create line above BSpline* (mid-token 'line')."""
        create = _cmd(
            "Sketcher_CreateLine",
            "Create line",
            workbench_id="SketcherWorkbench",
            workbench_name="Sketcher",
            current_workbench=True,
        )
        bspline = _cmd(
            "Sketcher_BSplineComb",
            "B-spline comb",
            workbench_id="SketcherWorkbench",
            workbench_name="Sketcher",
            current_workbench=True,
        )
        # Also cover id-style fallback labels as seen in the screenshot.
        bspline_id_label = _cmd(
            "Sketcher_BSplineIncreaseKnotMultiplicity",
            "Sketcher BSplineIncreaseKnotMultiplicity",
            workbench_id="SketcherWorkbench",
            workbench_name="Sketcher",
            current_workbench=True,
        )
        ranked = filter_commands(
            "line", [bspline, bspline_id_label, create]
        )
        self.assertEqual(ranked[0].name, "Sketcher_CreateLine")
        self.assertLess(score("line", create), score("line", bspline))
        self.assertLess(score("line", create), score("line", bspline_id_label))

    def test_label_display_path_uses_menu_text(self):
        """Ranking and display identity come from menu_text, not command id."""
        cmd = _cmd(
            "Sketcher_CreateLine",
            "Create line",
            workbench_id="SketcherWorkbench",
            workbench_name="Sketcher",
            current_workbench=True,
        )
        ranked = filter_commands("create line", [cmd])
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].menu_text, "Create line")
        self.assertNotEqual(ranked[0].menu_text, ranked[0].name)
        # Humanized fallback for missing MenuText still drops the module prefix.
        self.assertEqual(
            _humanize_command_name("Sketcher_CreateLine"), "Create Line"
        )
        self.assertEqual(
            _humanize_command_name("Sketcher_BSplineComb"), "B Spline Comb"
        )

    def test_label_beats_command_id(self):
        by_label = _cmd("Other_Thing", "Fillet", current_workbench=True)
        by_id = _cmd("Part_FilletEdge", "Blend edges", current_workbench=True)
        ranked = filter_commands("fillet", [by_id, by_label])
        self.assertEqual(ranked[0].name, "Other_Thing")

    def test_word_match_beats_midstring(self):
        word = _cmd("Sketcher_CreateLine", "Create line", current_workbench=True)
        mid = _cmd("Mesh_Pipeline", "Pipeline", current_workbench=True)
        ranked = filter_commands("line", [mid, word])
        self.assertEqual(ranked[0].name, "Sketcher_CreateLine")
        self.assertLess(score("line", word), score("line", mid))

    def test_camelcase_token_prefix_still_matches(self):
        """Token prefixes remain strong: 'spl' → BSpline via token 'spline'."""
        cmd = _cmd(
            "Sketcher_BSplineComb",
            "B-spline comb",
            current_workbench=True,
        )
        ranked = filter_commands("spl", [cmd])
        self.assertEqual(len(ranked), 1)

    def test_fuzzy_typo_still_matches(self):
        line = _cmd(
            "Sketcher_CreateLine",
            "Create line",
            workbench_id="SketcherWorkbench",
            current_workbench=True,
        )
        ranked = filter_commands("lne", [line])
        self.assertEqual(len(ranked), 1)

    def test_fuzzy_disabled_rejects_typo(self):
        line = _cmd(
            "Sketcher_CreateLine",
            "Create line",
            workbench_id="SketcherWorkbench",
            current_workbench=True,
        )
        ranked = filter_commands("lne", [line], allow_fuzzy=False)
        self.assertEqual(ranked, [])
        self.assertIsNone(score("lne", line, allow_fuzzy=False))

    def test_fuzzy_disabled_still_allows_exact(self):
        line = _cmd(
            "Sketcher_CreateLine",
            "Create line",
            current_workbench=True,
        )
        ranked = filter_commands("line", [line], allow_fuzzy=False)
        self.assertEqual(len(ranked), 1)

    def test_exact_beats_fuzzy(self):
        exact = _cmd("Draft_Line", "Line", current_workbench=True)
        fuzzy = _cmd("Draft_Link", "Link", current_workbench=True)
        # Query "line": exact label vs fuzzy edit to "link"
        ranked = filter_commands("line", [fuzzy, exact])
        self.assertEqual(ranked[0].name, "Draft_Line")
        self.assertLess(score("line", exact), score("line", fuzzy))

    def test_other_workbench_still_listed(self):
        other = _cmd(
            "Draft_Line",
            "Line",
            workbench_id="DraftWorkbench",
            workbench_name="Draft",
            current_workbench=False,
        )
        ranked = filter_commands("line", [other])
        self.assertEqual(ranked[0].name, "Draft_Line")

    def test_inactive_sorted_lower(self):
        active = _cmd("A_Cmd", "Box", active=True, current_workbench=True)
        inactive = _cmd("B_Cmd", "Box", active=False, current_workbench=True)
        ranked = filter_commands("box", [inactive, active])
        self.assertEqual(ranked[0].name, "A_Cmd")


if __name__ == "__main__":
    unittest.main()
