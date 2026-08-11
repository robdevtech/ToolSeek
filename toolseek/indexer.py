# SPDX-License-Identifier: LGPL-2.1-or-later
"""Collect registered FreeCAD commands and display metadata."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import FreeCADGui as Gui

# Do not list ToolSeek's own commands in palette results.
EXCLUDED_COMMANDS = frozenset({"ToolSeek_Open", "ToolSeek_Preferences"})

# "CreateLine" → Create, Line; "BSplineComb" → B, Spline, Comb.
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")


@dataclass(frozen=True)
class CommandInfo:
    """One searchable FreeCAD command."""

    name: str
    menu_text: str
    tooltip: str
    shortcut: str
    active: bool
    icon: Any  # QIcon or None
    workbench_id: str = ""
    workbench_name: str = ""
    current_workbench: bool = False


def _clean_label(text: str) -> str:
    return (text or "").replace("&", "").strip()


def _action_text(action) -> str:
    if action is None:
        return ""
    text = action.text() if hasattr(action, "text") else ""
    return _clean_label(text)


def _info_dict(cmd) -> dict:
    if cmd is None or not hasattr(cmd, "getInfo"):
        return {}
    try:
        info = cmd.getInfo()
    except Exception:
        return {}
    return info if isinstance(info, dict) else {}


def _resources_menu_text(cmd) -> str:
    """Prefer FreeCAD MenuText from command metadata when QAction text is empty."""
    info = _info_dict(cmd)
    for key in ("menuText", "MenuText", "menu_text"):
        value = info.get(key)
        if value:
            return _clean_label(str(value))
    return ""


def _humanize_command_name(name: str) -> str:
    """Fallback display when MenuText is unavailable: CamelCase → words."""
    if not name:
        return ""
    rest = name.split("_", 1)[1] if "_" in name else name
    pieces = _CAMEL_RE.findall(rest)
    if pieces:
        return " ".join(pieces)
    return rest.replace("_", " ").strip() or name


def _action_shortcut(action) -> str:
    if action is None or not hasattr(action, "shortcut"):
        return ""
    try:
        seq = action.shortcut()
        if seq is None:
            return ""
        text = seq.toString() if hasattr(seq, "toString") else str(seq)
        return (text or "").strip()
    except Exception:
        return ""


def _resources_shortcut(cmd) -> str:
    """Accel / shortcut from command getInfo when the QAction has none."""
    info = _info_dict(cmd)
    for key in ("accel", "Accel", "shortcut", "Shortcut", "keySequence"):
        value = info.get(key)
        if value:
            return str(value).strip()
    return ""


def _action_icon(action):
    if action is None or not hasattr(action, "icon"):
        return None
    try:
        icon = action.icon()
        if icon is None or (hasattr(icon, "isNull") and icon.isNull()):
            return None
        return icon
    except Exception:
        return None


def _qicon_type():
    try:
        from PySide import QtGui  # type: ignore
    except ImportError:
        try:
            from PySide2 import QtGui  # type: ignore
        except ImportError:
            from PySide6 import QtGui  # type: ignore
    return QtGui.QIcon


def _icon_if_valid(icon):
    if icon is not None and not (hasattr(icon, "isNull") and icon.isNull()):
        return icon
    return None


def _resources_icon(cmd):
    """Resolve Pixmap / icon from getInfo when the QAction has no icon.

    Avoid ``Gui.getIcon`` for names that are not already cached or loadable
    as a file/Qt resource. FreeCAD's BitmapFactory logs
    ``Cannot find icon: …`` for misses (e.g. Part_PickCurveNet's leftover
    Pixmap ``Test1``), which would spam the Report view on every palette open.
    """
    info = _info_dict(cmd)
    pixmap = ""
    for key in ("pixmap", "Pixmap", "icon"):
        value = info.get(key)
        if value:
            pixmap = str(value).strip()
            break
    if not pixmap:
        return None

    try:
        QIcon = _qicon_type()
    except Exception:
        QIcon = None

    # Absolute / relative filesystem path — quiet load.
    try:
        if os.path.isfile(pixmap) and QIcon is not None:
            found = _icon_if_valid(QIcon(pixmap))
            if found is not None:
                return found
    except Exception:
        pass

    # Qt resource path (e.g. :/icons/Part_Box.svg) — quiet load.
    if QIcon is not None and pixmap.startswith(":"):
        try:
            found = _icon_if_valid(QIcon(pixmap))
            if found is not None:
                return found
        except Exception:
            pass

    # Already in BitmapFactory cache — getIcon will not warn.
    is_cached = getattr(Gui, "isIconCached", None)
    if callable(is_cached):
        try:
            if is_cached(pixmap):
                getter = getattr(Gui, "getIcon", None)
                if callable(getter):
                    return _icon_if_valid(getter(pixmap))
        except Exception:
            pass

    # Do not call Gui.getIcon for uncached / unknown names.
    return None


def _command_active(cmd) -> bool:
    """Best-effort active flag.

    Do **not** call Command.isActive(): on FreeCAD 1.1 / Qt6 some commands
    (e.g. expression helpers) touch deleted QActions and can SIGSEGV, which
    Python cannot catch.
    """
    info = _info_dict(cmd)
    if "active" in info:
        return bool(info["active"])
    return True


def _active_workbench_id() -> str:
    try:
        wb = Gui.activeWorkbench()
    except Exception:
        return ""
    if wb is None:
        return ""
    try:
        name = wb.name() if callable(getattr(wb, "name", None)) else getattr(wb, "name", "")
        return str(name or "")
    except Exception:
        return ""


def _workbench_prefix_map() -> dict[str, tuple[str, str]]:
    """Map casefolded command-name prefixes to (workbench_id, display_name)."""
    mapping: dict[str, tuple[str, str]] = {}
    try:
        workbenches = Gui.listWorkbenches()
    except Exception:
        workbenches = {}

    if not isinstance(workbenches, dict):
        return mapping

    for wb_id, display in workbenches.items():
        wb_id_s = str(wb_id or "")
        if not wb_id_s:
            continue
        display_s = str(display or "").strip() or wb_id_s
        short = wb_id_s
        if short.endswith("Workbench"):
            short = short[: -len("Workbench")]
        for key in (wb_id_s, short):
            folded = key.casefold()
            if folded and folded not in mapping:
                mapping[folded] = (wb_id_s, display_s)
    return mapping


def _command_prefix(name: str) -> str:
    if not name or "_" not in name:
        return ""
    return name.split("_", 1)[0]


def _resolve_workbench(
    name: str,
    prefix_map: dict[str, tuple[str, str]],
    active_id: str,
) -> tuple[str, str, bool]:
    """Return (workbench_id, workbench_name, current_workbench).

    *workbench_id* is only set when it matches ``Gui.listWorkbenches()``,
    so callers can safely pass it to ``Gui.activateWorkbench``. Unknown
    prefixes still get a display *workbench_name* (the command module
    prefix) for UI cues.
    """
    prefix = _command_prefix(name)
    wb_id = ""
    wb_name = ""

    if prefix:
        hit = prefix_map.get(prefix.casefold())
        if hit is not None:
            wb_id, wb_name = hit
        else:
            wb_name = prefix

    current = False
    if active_id:
        if wb_id and wb_id == active_id:
            current = True
        elif prefix:
            active_short = active_id
            if active_short.endswith("Workbench"):
                active_short = active_short[: -len("Workbench")]
            current = prefix.casefold() == active_short.casefold()

    return wb_id, wb_name, current


def _build_one(
    name: str,
    prefix_map: dict[str, tuple[str, str]],
    active_id: str,
) -> Optional[CommandInfo]:
    if not name or name in EXCLUDED_COMMANDS:
        return None

    cmd = None
    try:
        cmd = Gui.Command.get(name)
    except Exception:
        cmd = None

    action = None
    if cmd is not None:
        try:
            if hasattr(cmd, "getAction"):
                action = cmd.getAction()
        except Exception:
            action = None

    menu_text = _action_text(action) or _resources_menu_text(cmd)
    if not menu_text:
        # Last resort: readable CamelCase form of the internal id (no module prefix).
        menu_text = _humanize_command_name(name)

    tooltip = ""
    if action is not None and hasattr(action, "toolTip"):
        try:
            tooltip = (action.toolTip() or "").strip()
        except Exception:
            tooltip = ""
    if not tooltip:
        info = _info_dict(cmd)
        for key in ("toolTip", "ToolTip", "tooltip"):
            value = info.get(key)
            if value:
                tooltip = str(value).strip()
                break

    icon = _action_icon(action) or _resources_icon(cmd)

    wb_id, wb_name, current = _resolve_workbench(name, prefix_map, active_id)

    shortcut = _action_shortcut(action) or _resources_shortcut(cmd)

    return CommandInfo(
        name=name,
        menu_text=menu_text,
        tooltip=tooltip,
        shortcut=shortcut,
        active=_command_active(cmd) if cmd is not None else True,
        icon=icon,
        workbench_id=wb_id,
        workbench_name=wb_name,
        current_workbench=current,
    )


def build() -> list[CommandInfo]:
    """Return metadata for all currently registered FreeCAD commands."""
    try:
        names = Gui.listCommands()
    except Exception:
        try:
            names = Gui.Command.listAll()
        except Exception:
            names = []

    prefix_map = _workbench_prefix_map()
    active_id = _active_workbench_id()

    results: list[CommandInfo] = []
    for name in names:
        info = _build_one(name, prefix_map, active_id)
        if info is not None:
            results.append(info)

    # Stable order: current WB, then active, then by menu text.
    results.sort(
        key=lambda c: (
            not c.current_workbench,
            not c.active,
            c.menu_text.casefold(),
            c.name.casefold(),
        )
    )
    return results
