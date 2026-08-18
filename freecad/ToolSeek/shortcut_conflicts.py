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
        "ToolSeek_ShortcutRecorder",  # prefs QKeySequenceEdit
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


def is_toolseek_owned_name(name: str) -> bool:
    """True for ToolSeek binders, menu actions, commands, and recorder widgets."""
    n = (name or "").strip()
    if not n:
        return False
    if (
        n in TOOLSEEK_SHORTCUT_OBJECT_NAMES
        or n in TOOLSEEK_ACTION_OBJECT_NAMES
        or n in TOOLSEEK_COMMAND_NAMES
    ):
        return True
    return n.startswith("ToolSeek_") or n.startswith("FCSearch_")


def _object_name(obj) -> str:
    try:
        return (obj.objectName() or "").strip()
    except Exception:
        return ""


def _iter_parents(obj):
    cur = obj
    seen: set[int] = set()
    while cur is not None:
        ident = id(cur)
        if ident in seen:
            break
        seen.add(ident)
        yield cur
        try:
            cur = cur.parent()
        except Exception:
            break


def _owned_by_ignored_object(obj, ignore_objects) -> bool:
    if not ignore_objects:
        return False
    ignore_ids = {id(item) for item in ignore_objects if item is not None}
    if not ignore_ids:
        return False
    return any(id(ancestor) in ignore_ids for ancestor in _iter_parents(obj))


def qshortcut_should_skip(sc, *, ignore_objects=()) -> bool:
    """True if *sc* is ToolSeek-owned, disabled, or an unnamed leftover.

    Unnamed QShortcuts are FreeCAD/recorder leftovers (often Ctrl+Space).
    Startup install deletes them; conflict checks must not treat them as
    third-party bindings or Reset cannot restore the default.
    """
    try:
        if hasattr(sc, "isEnabled") and not sc.isEnabled():
            return True
    except Exception:
        pass
    name = _object_name(sc)
    if not name:
        return True
    if is_toolseek_owned_name(name):
        return True
    if _owned_by_ignored_object(sc, ignore_objects):
        return True
    for ancestor in _iter_parents(sc):
        if is_toolseek_owned_name(_object_name(ancestor)):
            return True
    return False


def qaction_should_skip(action, *, ignore_objects=()) -> bool:
    """True if *action* is a ToolSeek menu/command action."""
    name = _object_name(action)
    if is_toolseek_owned_name(name):
        return True
    try:
        text = (action.text() or "").replace("&", "").strip()
    except Exception:
        text = ""
    if text.casefold().startswith("toolseek"):
        return True
    return _owned_by_ignored_object(action, ignore_objects)


def clear_unnamed_shortcuts_for_sequence(mw, sequence: str) -> int:
    """Remove unnamed QShortcuts matching *sequence* (startup leftovers).

    FreeCAD / prior binders sometimes leave an unnamed Ctrl+Space QShortcut.
    Treating that as a hard conflict left ToolSeek with no binding at all.
    Named foreign shortcuts are left untouched.
    """
    target = normalize_shortcut(sequence)
    if not target or mw is None:
        return 0
    try:
        shortcuts = list(mw.findChildren(QShortcut))
    except Exception:
        return 0
    removed = 0
    for sc in shortcuts:
        try:
            name = _object_name(sc)
        except Exception:
            continue
        if name:
            # Keep named binders (including ToolSeek's own) intact.
            continue
        try:
            key = sc.key()
        except Exception:
            continue
        if not sequences_match(key, target):
            continue
        try:
            if hasattr(sc, "setEnabled"):
                sc.setEnabled(False)
            sc.deleteLater()
            removed += 1
        except Exception:
            continue
    return removed


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
    ignore_objects: tuple | list | None = None,
) -> list[str]:
    """Return human-readable conflict labels for *sequence* on *mw*.

    Ignores ToolSeek's own QShortcut / menu actions / commands (by objectName,
    parent chain, and command id) so rebinding or Reset is not a false
    positive. Unnamed leftover QShortcuts are ignored (cleared on apply).
    Optional *ignore_objects* skips those Qt objects and their descendants
    (the prefs recorder, the live ToolSeek binder). Optional
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

    skipped = tuple(ignore_objects or ())

    if mw is not None:
        try:
            for sc in list(mw.findChildren(QShortcut)):
                if qshortcut_should_skip(sc, ignore_objects=skipped):
                    continue
                try:
                    key = sc.key()
                except Exception:
                    continue
                if _matches_target(key):
                    _add(f"QShortcut ({_object_name(sc) or 'unnamed'})")
        except Exception:
            pass

        try:
            for action in list(mw.findChildren(QAction)):
                if qaction_should_skip(action, ignore_objects=skipped):
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
        if is_toolseek_owned_name(cmd_name):
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
