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
from .shortcut_conflicts import normalize_shortcut

QKeySequenceEdit = getattr(QtWidgets, "QKeySequenceEdit", None)


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


def set_recorded_shortcut(edit, text: str) -> None:
    """Show *text* (or the default) in a recorder widget."""
    value = (text or "").strip() or prefs.DEFAULT_OPEN_SHORTCUT
    if edit is None:
        return
    if QKeySequenceEdit is not None and isinstance(edit, QKeySequenceEdit):
        try:
            edit.setKeySequence(QtGui.QKeySequence(value))
            return
        except Exception:
            pass
    try:
        edit.setText(value)
    except Exception:
        return


def _configure_key_sequence_edit(edit) -> None:
    tip = (
        "Click this field, then press the key combination that should open "
        "the palette (e.g. Ctrl+Space, Alt+P). "
        "ToolSeek will not override an existing FreeCAD shortcut."
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
        event.accept()


def create_shortcut_recorder(parent=None):
    """Return a QKeySequenceEdit (or fallback) for capturing a shortcut chord."""
    if QKeySequenceEdit is not None:
        edit = QKeySequenceEdit(parent)
        _configure_key_sequence_edit(edit)
        return edit
    return _FallbackKeySequenceEdit(parent)


def create_reset_shortcut_button(parent=None) -> QtWidgets.QPushButton:
    btn = QtWidgets.QPushButton("Reset", parent)
    btn.setToolTip(f"Restore default ({prefs.DEFAULT_OPEN_SHORTCUT})")
    return btn
