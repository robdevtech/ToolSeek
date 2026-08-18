# SPDX-License-Identifier: LGPL-2.1-or-later
"""Key-sequence recording widgets for ToolSeek open-palette shortcut prefs."""

from __future__ import annotations

try:
    from PySide import QtCore, QtGui, QtWidgets  # type: ignore
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
    except ImportError:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from . import prefs
from .shortcut_conflicts import (
    clear_unnamed_shortcuts_for_sequence,
    find_shortcut_conflicts,
    normalize_shortcut,
    sequences_match,
)

QKeySequenceEdit = getattr(QtWidgets, "QKeySequenceEdit", None)
QTimer = QtCore.QTimer
QMessageBox = QtWidgets.QMessageBox

_MODIFIER_TOKENS = frozenset(
    {"ctrl", "control", "shift", "alt", "meta", "cmd", "command"}
)


def key_sequence_to_portable(sequence) -> str:
    """Convert a QKeySequence (or string) to a portable shortcut string."""
    if sequence is None:
        return ""
    try:
        if hasattr(sequence, "isEmpty") and sequence.isEmpty():
            return ""
    except Exception:
        pass
    try:
        if isinstance(sequence, str):
            return normalize_shortcut(sequence)
        if hasattr(QtGui.QKeySequence, "SequenceFormat"):
            text = sequence.toString(QtGui.QKeySequence.SequenceFormat.PortableText)
        elif hasattr(QtGui.QKeySequence, "PortableText"):
            text = sequence.toString(QtGui.QKeySequence.PortableText)
        else:
            text = sequence.toString() if hasattr(sequence, "toString") else str(sequence)
        return normalize_shortcut(text or "")
    except Exception:
        try:
            return normalize_shortcut(str(sequence))
        except Exception:
            return ""


def recorded_shortcut_text(edit) -> str:
    """Portable shortcut from a recorder widget; empty means 'use default'."""
    if edit is None:
        return ""
    if QKeySequenceEdit is not None and isinstance(edit, QKeySequenceEdit):
        try:
            return key_sequence_to_portable(edit.keySequence())
        except Exception:
            return ""
    try:
        return normalize_shortcut(edit.text())
    except Exception:
        return ""


def set_recorded_shortcut(edit, text: str, *, validate: bool = False) -> None:
    """Show *text* (or the default) in a recorder widget."""
    value = (text or "").strip() or prefs.DEFAULT_OPEN_SHORTCUT
    if edit is None:
        return
    setattr(edit, "_suppress_conflict_check", True)
    try:
        if QKeySequenceEdit is not None and isinstance(edit, QKeySequenceEdit):
            try:
                edit.setKeySequence(QtGui.QKeySequence(value))
            except Exception:
                try:
                    edit.setText(value)
                except Exception:
                    return
        else:
            try:
                edit.setText(value)
            except Exception:
                return
        if not validate:
            edit._accepted_shortcut = recorded_shortcut_text(edit) or value
    finally:
        setattr(edit, "_suppress_conflict_check", False)
    if validate:
        _validate_recorder(edit, interactive=True, defer=False)


def reset_recorded_shortcut(edit) -> None:
    """Restore the default open shortcut, allowing ToolSeek to reclaim it.

    Clears unnamed leftover QShortcuts for the default chord first (same as
    startup install) so Reset is not rolled back as a false conflict.
    """
    default = prefs.DEFAULT_OPEN_SHORTCUT
    try:
        import FreeCADGui as Gui

        clear_unnamed_shortcuts_for_sequence(Gui.getMainWindow(), default)
    except Exception:
        pass
    set_recorded_shortcut(edit, default, validate=True)


def _is_incomplete_chord(text: str) -> bool:
    parts = [
        part.strip().casefold()
        for part in normalize_shortcut(text).replace("-", "+").split("+")
        if part.strip()
    ]
    return bool(parts) and all(part in _MODIFIER_TOKENS for part in parts)


def _configure_key_sequence_edit(edit) -> None:
    tip = (
        "Click this field, then press the key combination that should open "
        "the palette (e.g. Ctrl+Space, Alt+P). "
        "A shortcut already used elsewhere is rejected immediately."
    )
    try:
        edit.setToolTip(tip)
    except Exception:
        pass
    # Single chord is enough for an open hotkey.
    for name, args in (
        ("setMaximumSequenceLength", (1,)),
        ("setClearButtonEnabled", (True,)),
    ):
        setter = getattr(edit, name, None)
        if callable(setter):
            try:
                setter(*args)
            except Exception:
                pass


def _conflicts_for(edit, seq: str) -> list[str]:
    conflicts: list[str] = []
    seen: set[str] = set()

    def _add(label: str) -> None:
        key = label.casefold()
        if not label or key in seen:
            return
        seen.add(key)
        conflicts.append(label)

    try:
        import FreeCADGui as Gui

        mw = Gui.getMainWindow()
        for label in (
            find_shortcut_conflicts(mw, seq, ignore_objects=(edit,)) or []
        ):
            _add(label)
    except Exception:
        pass
    extra = getattr(edit, "_extra_conflicts", None)
    if callable(extra):
        try:
            for label in extra(seq) or []:
                _add(str(label))
        except Exception:
            pass
    return conflicts


def _warn_live_conflict(edit, seq: str, conflicts: list[str]) -> None:
    title = getattr(edit, "_shortcut_guard_title", "ToolSeek")
    detail = "; ".join(conflicts[:8])
    try:
        import FreeCAD as App

        App.Console.PrintWarning(
            f"{title}: shortcut '{seq}' is already used ({detail}); "
            "keeping the previous shortcut.\n"
        )
    except Exception:
        pass
    lines = "\n".join(f"• {c}" for c in conflicts[:12])
    if len(conflicts) > 12:
        lines += f"\n• …and {len(conflicts) - 12} more"
    parent = None
    try:
        parent = edit.window() if edit is not None else None
    except Exception:
        parent = None
    try:
        QMessageBox.warning(
            parent,
            title,
            (
                f"Cannot use shortcut “{seq}”.\n\n"
                "It is already used:\n"
                f"{lines}\n\n"
                "The previous shortcut was kept."
            ),
        )
    except Exception:
        pass


def _revert_recorder(edit) -> None:
    fallback = (
        getattr(edit, "_accepted_shortcut", "") or prefs.DEFAULT_OPEN_SHORTCUT
    )
    set_recorded_shortcut(edit, fallback, validate=False)


def _validate_recorder(edit, *, interactive: bool, defer: bool) -> bool:
    if edit is None or getattr(edit, "_suppress_conflict_check", False):
        return True
    seq = recorded_shortcut_text(edit)
    if not seq or _is_incomplete_chord(seq):
        return True
    accepted = getattr(edit, "_accepted_shortcut", "") or ""
    if accepted and sequences_match(seq, accepted):
        return True
    # Self-rebind: chord already owned by ToolSeek (Reset to default while
    # the binder is still on Ctrl+Space, or re-recording the live shortcut).
    try:
        from . import bootstrap

        applied = getattr(bootstrap, "_applied_shortcut", "") or ""
        if applied and sequences_match(seq, applied):
            edit._accepted_shortcut = seq
            return True
    except Exception:
        pass
    conflicts = _conflicts_for(edit, seq)
    if not conflicts:
        edit._accepted_shortcut = seq
        return True

    _revert_recorder(edit)

    def _dialog() -> None:
        try:
            if interactive:
                _warn_live_conflict(edit, seq, conflicts)
        finally:
            setattr(edit, "_conflict_reject_pending", False)

    if not interactive:
        return False
    if defer:
        if getattr(edit, "_conflict_reject_pending", False):
            return False
        edit._conflict_reject_pending = True
        QTimer.singleShot(0, _dialog)
        return False
    _dialog()
    return False


def _attach_live_conflict_guard(edit) -> None:
    edit._shortcut_guard_title = "ToolSeek"
    edit._shortcut_default = prefs.DEFAULT_OPEN_SHORTCUT
    if not getattr(edit, "_accepted_shortcut", ""):
        edit._accepted_shortcut = recorded_shortcut_text(edit) or prefs.DEFAULT_OPEN_SHORTCUT
    if hasattr(edit, "keySequenceChanged"):
        edit.keySequenceChanged.connect(
            lambda *_args: _validate_recorder(edit, interactive=True, defer=True)
        )


class _FallbackKeySequenceEdit(QtWidgets.QLineEdit):
    """Minimal key recorder when QKeySequenceEdit is unavailable (very old Qt)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Click then press keys")
        if hasattr(self, "setClearButtonEnabled"):
            self.setClearButtonEnabled(True)
        _configure_key_sequence_edit(self)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        try:
            key = event.key()
        except Exception:
            super().keyPressEvent(event)
            return

        # Let Escape clear; Tab for focus traversal.
        try:
            escape = QtCore.Qt.Key.Key_Escape
            tab = QtCore.Qt.Key.Key_Tab
            backtab = QtCore.Qt.Key.Key_Backtab
        except AttributeError:
            escape = QtCore.Qt.Key_Escape
            tab = QtCore.Qt.Key_Tab
            backtab = QtCore.Qt.Key_Backtab

        if key in (tab, backtab):
            super().keyPressEvent(event)
            return
        if key == escape:
            self.clear()
            event.accept()
            return

        # Ignore modifier-only presses; wait for the key they modify.
        try:
            modifiers_only = {
                QtCore.Qt.Key.Key_Control,
                QtCore.Qt.Key.Key_Shift,
                QtCore.Qt.Key.Key_Alt,
                QtCore.Qt.Key.Key_Meta,
                QtCore.Qt.Key.Key_AltGr,
            }
        except AttributeError:
            modifiers_only = {
                QtCore.Qt.Key_Control,
                QtCore.Qt.Key_Shift,
                QtCore.Qt.Key_Alt,
                QtCore.Qt.Key_Meta,
            }
        if key in modifiers_only:
            event.accept()
            return

        try:
            seq = QtGui.QKeySequence(event.keyCombination())
        except Exception:
            try:
                seq = QtGui.QKeySequence(int(event.modifiers()) | key)
            except Exception:
                super().keyPressEvent(event)
                return

        portable = key_sequence_to_portable(seq)
        if portable:
            self.setText(portable)
            _validate_recorder(self, interactive=True, defer=True)
        event.accept()


def create_shortcut_recorder(parent=None):
    """Return a QKeySequenceEdit (or fallback) for capturing a shortcut chord."""
    if QKeySequenceEdit is not None:
        edit = QKeySequenceEdit(parent)
        _configure_key_sequence_edit(edit)
    else:
        edit = _FallbackKeySequenceEdit(parent)
    try:
        edit.setObjectName("ToolSeek_ShortcutRecorder")
    except Exception:
        pass
    _attach_live_conflict_guard(edit)
    return edit


def create_reset_shortcut_button(parent=None) -> QtWidgets.QPushButton:
    btn = QtWidgets.QPushButton("Reset", parent)
    btn.setToolTip(f"Restore default ({prefs.DEFAULT_OPEN_SHORTCUT})")
    return btn
