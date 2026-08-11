# SPDX-License-Identifier: LGPL-2.1-or-later
"""Detect keyboard shortcut collisions with existing FreeCAD / Qt bindings."""

from __future__ import annotations

import FreeCADGui as Gui

try:
    from PySide import QtGui, QtWidgets  # type: ignore
except ImportError:
    try:
        from PySide2 import QtGui, QtWidgets  # type: ignore
    except ImportError:
        from PySide6 import QtGui, QtWidgets  # type: ignore

QAction = getattr(QtGui, "QAction", None) or getattr(QtWidgets, "QAction")
QShortcut = getattr(QtGui, "QShortcut", None) or getattr(QtWidgets, "QShortcut")

# Object names owned by ToolSeek — never treated as foreign conflicts.
TOOLSEEK_SHORTCUT_OBJECT_NAMES = frozenset(
    {
        "ToolSeek_OpenShortcut",
        "ToolSeek_CtrlSpaceShortcut",  # legacy object name
        "FCSearch_CtrlSpaceShortcut",  # pre-rename binder
    }
)
TOOLSEEK_ACTION_OBJECT_NAMES = frozenset(
    {
        "ToolSeek_ToolsAction",
        "ToolSeek_PrefsAction",
    }
)
TOOLSEEK_COMMAND_NAMES = frozenset(
    {
        "ToolSeek_Open",
        "ToolSeek_Preferences",
    }
)


def normalize_shortcut(text: str) -> str:
    """Return a portable QKeySequence string, or '' if empty/invalid."""
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        seq = QtGui.QKeySequence(raw)
    except Exception:
        return raw
    try:
        if hasattr(QtGui.QKeySequence, "SequenceFormat"):
            out = seq.toString(QtGui.QKeySequence.SequenceFormat.PortableText)
        elif hasattr(QtGui.QKeySequence, "PortableText"):
            out = seq.toString(QtGui.QKeySequence.PortableText)
        else:
            out = seq.toString()
        return (out or "").strip()
    except Exception:
        try:
            return (seq.toString() or "").strip()
        except Exception:
            return raw


def sequences_match(a, b) -> bool:
    """True when two key sequences refer to the same chord."""
    if a is None or b is None:
        return False
    try:
        sa = a if isinstance(a, QtGui.QKeySequence) else QtGui.QKeySequence(str(a))
        sb = b if isinstance(b, QtGui.QKeySequence) else QtGui.QKeySequence(str(b))
    except Exception:
        return str(a).strip().casefold() == str(b).strip().casefold()
    try:
        if hasattr(sa, "isEmpty") and (sa.isEmpty() or sb.isEmpty()):
            return False
    except Exception:
        pass
    na = normalize_shortcut(sa.toString() if hasattr(sa, "toString") else str(sa))
    nb = normalize_shortcut(sb.toString() if hasattr(sb, "toString") else str(sb))
    if not na or not nb:
        return False
    return na.casefold() == nb.casefold()


def _action_label(action) -> str:
    try:
        text = (action.text() or "").replace("&", "").strip()
    except Exception:
        text = ""
    if text:
        return text
    try:
        name = (action.objectName() or "").strip()
    except Exception:
        name = ""
    return name or "unnamed action"


def _iter_action_sequences(action):
    try:
        if hasattr(action, "shortcuts"):
            for seq in list(action.shortcuts() or []):
                yield seq
            return
    except Exception:
        pass
    try:
        if hasattr(action, "shortcut"):
            yield action.shortcut()
    except Exception:
        return


def find_shortcut_conflicts(
    mw,
    sequence: str,
    *,
    ignore_sequences: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """Return human-readable conflict labels for *sequence* on *mw*.

    Ignores ToolSeek's own QShortcut / menu actions / commands so rebinding the
    same or a new chord does not false-positive on ToolSeek itself. Optional
    *ignore_sequences* are additional chords to skip (normally unused).
    """
    target = normalize_shortcut(sequence)
    if not target:
        return []

    ignore_norm = {
        normalize_shortcut(s).casefold()
        for s in (ignore_sequences or ())
        if normalize_shortcut(s)
    }

    conflicts: list[str] = []
    seen: set[str] = set()

    def _add(label: str) -> None:
        key = label.casefold()
        if key in seen:
            return
        seen.add(key)
        conflicts.append(label)

    def _matches_target(seq) -> bool:
        if not sequences_match(seq, target):
            return False
        try:
            norm = normalize_shortcut(
                seq.toString() if hasattr(seq, "toString") else str(seq)
            ).casefold()
        except Exception:
            norm = ""
        if norm and norm in ignore_norm:
            return False
        return True

    if mw is not None:
        try:
            for sc in list(mw.findChildren(QShortcut)):
                try:
                    name = sc.objectName() or ""
                except Exception:
                    name = ""
                if name in TOOLSEEK_SHORTCUT_OBJECT_NAMES:
                    continue
                try:
                    if hasattr(sc, "isEnabled") and not sc.isEnabled():
                        continue
                except Exception:
                    pass
                try:
                    key = sc.key()
                except Exception:
                    continue
                if _matches_target(key):
                    _add(f"QShortcut ({name or 'unnamed'})")
        except Exception:
            pass

        try:
            for action in list(mw.findChildren(QAction)):
                try:
                    name = action.objectName() or ""
                except Exception:
                    name = ""
                if name in TOOLSEEK_ACTION_OBJECT_NAMES:
                    continue
                if name in TOOLSEEK_SHORTCUT_OBJECT_NAMES:
                    continue
                for seq in _iter_action_sequences(action):
                    if _matches_target(seq):
                        _add(f"Action: {_action_label(action)}")
                        break
        except Exception:
            pass

    # FreeCAD command Accel bindings (Customize → Keyboard).
    try:
        names = list(Gui.listCommands())
    except Exception:
        try:
            names = list(Gui.Command.listAll())
        except Exception:
            names = []

    for cmd_name in names:
        if cmd_name in TOOLSEEK_COMMAND_NAMES:
            continue
        try:
            cmd = Gui.Command.get(cmd_name)
        except Exception:
            continue
        if cmd is None:
            continue
        accel = ""
        try:
            if hasattr(cmd, "getInfo"):
                info = cmd.getInfo() or {}
                if isinstance(info, dict):
                    for key in ("accel", "Accel", "shortcut", "Shortcut"):
                        value = info.get(key)
                        if value:
                            accel = str(value).strip()
                            break
        except Exception:
            accel = ""
        if not accel and hasattr(cmd, "getShortcut"):
            try:
                accel = str(cmd.getShortcut() or "").strip()
            except Exception:
                accel = ""
        if accel and _matches_target(accel):
            _add(f"Command: {cmd_name}")

    return conflicts
