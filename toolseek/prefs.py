# SPDX-License-Identifier: LGPL-2.1-or-later
"""Preference access for ToolSeek."""

from __future__ import annotations

import FreeCAD as App

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/ToolSeek"

# PrefComboBox stores the combo index as Int.
RESULT_STYLES = ("icons", "words")
DEFAULT_RESULT_STYLE = "icons"


def _group():
    return App.ParamGet(PARAM_PATH)


def param_group():
    """Public handle for attaching preference observers."""
    return _group()


def result_style_index() -> int:
    """0=Icons (icons + labels), 1=Words (labels only)."""
    idx = int(_group().GetInt("ResultStyle", 0))
    if 0 <= idx < len(RESULT_STYLES):
        return idx
    return 0


def result_style() -> str:
    return RESULT_STYLES[result_style_index()]


def set_result_style(value: str | int) -> None:
    if isinstance(value, int):
        idx = value
    else:
        style = str(value).strip().lower()
        if style not in RESULT_STYLES:
            raise ValueError(f"Invalid result style: {value}")
        idx = RESULT_STYLES.index(style)
    if not 0 <= idx < len(RESULT_STYLES):
        raise ValueError(f"Invalid result style index: {value}")
    _group().SetInt("ResultStyle", idx)


def show_icons() -> bool:
    """True when results should show command icons beside labels."""
    return result_style() == "icons"


def allow_fuzzy() -> bool:
    return _group().GetBool("AllowFuzzy", True)


def set_allow_fuzzy(value: bool) -> None:
    _group().SetBool("AllowFuzzy", bool(value))


def switch_workbench() -> bool:
    """When True, selecting another workbench's command activates that WB first."""
    return _group().GetBool("SwitchWorkbench", True)


def set_switch_workbench(value: bool) -> None:
    _group().SetBool("SwitchWorkbench", bool(value))
