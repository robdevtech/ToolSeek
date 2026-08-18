# SPDX-License-Identifier: LGPL-2.1-or-later
"""Edit → Preferences → ToolSeek page with key-sequence recording."""

from __future__ import annotations

import os

import FreeCAD as App
import FreeCADGui as Gui

from . import prefs
from .shortcut_edit import (
    create_reset_shortcut_button,
    create_shortcut_recorder,
    recorded_shortcut_text,
    reset_recorded_shortcut,
    set_recorded_shortcut,
)

try:
    from PySide import QtWidgets  # type: ignore
except ImportError:
    try:
        from PySide2 import QtWidgets  # type: ignore
    except ImportError:
        from PySide6 import QtWidgets  # type: ignore


def _ui_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "resources",
        "ui",
        "preferences.ui",
    )


class ToolSeekPreferencePage:
    """Python preference page: loads preferences.ui and records shortcuts."""

    def __init__(self, parent=None) -> None:
        ui = _ui_path()
        if not os.path.isfile(ui):
            App.Console.PrintWarning(f"ToolSeek: preference UI missing: {ui}\n")
            self.form = QtWidgets.QWidget()
            self.open_shortcut = create_shortcut_recorder(self.form)
            self._pref_line = None
            return

        self.form = Gui.PySideUic.loadUi(ui)
        self._pref_line = getattr(self.form, "lineOpenShortcut", None)
        self._wire_shortcut_recorder()

    def _wire_shortcut_recorder(self) -> None:
        """Hide PrefLineEdit; insert QKeySequenceEdit + Reset in its place."""
        layout = getattr(self.form, "openShortcutLayout", None)
        line = self._pref_line
        if layout is None or line is None:
            App.Console.PrintWarning(
                "ToolSeek: preference shortcut layout missing; "
                "falling back to plain recorder\n"
            )
            self.open_shortcut = create_shortcut_recorder(self.form)
            return

        # Keep PrefLineEdit in the tree (hidden) so its prefEntry metadata
        # remains available if FreeCAD inspects children; we sync text on save.
        try:
            line.hide()
            layout.removeWidget(line)
        except Exception:
            pass

        self.open_shortcut = create_shortcut_recorder(self.form)
        self.reset_shortcut = create_reset_shortcut_button(self.form)
        self.reset_shortcut.clicked.connect(self._reset_shortcut_field)

        layout.addWidget(self.open_shortcut, 1)
        layout.addWidget(self.reset_shortcut)

        hint = getattr(self.form, "labelOpenShortcutHint", None)
        if hint is not None:
            try:
                hint.setText(
                    "Click the shortcut field, then press keys. "
                    "Reset restores Ctrl+Space. "
                    "A shortcut already used elsewhere is rejected immediately."
                )
            except Exception:
                pass

    def _reset_shortcut_field(self) -> None:
        reset_recorded_shortcut(self.open_shortcut)
        if self._pref_line is not None:
            try:
                self._pref_line.setText(
                    recorded_shortcut_text(self.open_shortcut)
                    or prefs.DEFAULT_OPEN_SHORTCUT
                )
            except Exception:
                pass

    def loadSettings(self) -> None:
        form = self.form
        try:
            combo = getattr(form, "comboResultStyle", None)
            if combo is not None:
                combo.setCurrentIndex(prefs.result_style_index())
            fuzzy = getattr(form, "checkAllowFuzzy", None)
            if fuzzy is not None:
                fuzzy.setChecked(prefs.allow_fuzzy())
            switch = getattr(form, "checkSwitchWorkbench", None)
            if switch is not None:
                switch.setChecked(prefs.switch_workbench())
        except Exception as exc:  # noqa: BLE001
            App.Console.PrintWarning(
                f"ToolSeek: preference loadSettings failed: {exc}\n"
            )

        current = prefs.open_shortcut()
        set_recorded_shortcut(getattr(self, "open_shortcut", None), current)
        if self._pref_line is not None:
            try:
                self._pref_line.setText(current)
            except Exception:
                pass

    def saveSettings(self) -> None:
        form = self.form
        try:
            combo = getattr(form, "comboResultStyle", None)
            if combo is not None:
                prefs.set_result_style(int(combo.currentIndex()))
            fuzzy = getattr(form, "checkAllowFuzzy", None)
            if fuzzy is not None:
                prefs.set_allow_fuzzy(fuzzy.isChecked())
            switch = getattr(form, "checkSwitchWorkbench", None)
            if switch is not None:
                prefs.set_switch_workbench(switch.isChecked())
        except Exception as exc:  # noqa: BLE001
            App.Console.PrintWarning(
                f"ToolSeek: preference saveSettings failed: {exc}\n"
            )

        edit = getattr(self, "open_shortcut", None)
        desired = recorded_shortcut_text(edit) or prefs.DEFAULT_OPEN_SHORTCUT
        if self._pref_line is not None:
            try:
                self._pref_line.setText(desired)
            except Exception:
                pass

        from . import bootstrap

        if not bootstrap.try_set_open_shortcut(desired, interactive=True):
            applied = prefs.open_shortcut()
            set_recorded_shortcut(edit, applied)
            if self._pref_line is not None:
                try:
                    self._pref_line.setText(applied)
                except Exception:
                    pass
