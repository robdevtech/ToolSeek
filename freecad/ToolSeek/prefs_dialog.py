# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small preference dialog (also backed by ParamGet / preference page)."""

from __future__ import annotations

try:
    from PySide import QtWidgets  # type: ignore
except ImportError:
    try:
        from PySide2 import QtWidgets  # type: ignore
    except ImportError:
        from PySide6 import QtWidgets  # type: ignore

from . import prefs
from .shortcut_edit import (
    create_reset_shortcut_button,
    create_shortcut_recorder,
    recorded_shortcut_text,
    set_recorded_shortcut,
)


class PreferencesDialog(QtWidgets.QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ToolSeek")
        self.setModal(True)
        self.resize(480, 300)

        self.result_style = QtWidgets.QComboBox()
        self.result_style.addItem("Icons", "icons")
        self.result_style.addItem("Words", "words")
        self.result_style.setToolTip(
            "Icons: show command icons beside labels. "
            "Words: text-only list (labels, no icons)."
        )

        self.allow_fuzzy = QtWidgets.QCheckBox("Allow fuzzy matching")
        self.allow_fuzzy.setChecked(True)
        self.allow_fuzzy.setToolTip(
            "When on, small typos and subsequences can still match. "
            "Exact, prefix, and word matches always rank higher."
        )

        self.switch_wb = QtWidgets.QCheckBox(
            "Allow selection to switch workbench"
        )
        self.switch_wb.setChecked(True)
        self.switch_wb.setToolTip(
            "When on, running a command from another workbench activates "
            "that workbench first. When off, the command still runs without "
            "switching workbenches."
        )

        self.open_shortcut = create_shortcut_recorder()
        self.reset_shortcut = create_reset_shortcut_button()
        self.reset_shortcut.clicked.connect(self._reset_shortcut_field)

        shortcut_row = QtWidgets.QHBoxLayout()
        shortcut_row.addWidget(self.open_shortcut, 1)
        shortcut_row.addWidget(self.reset_shortcut)

        shortcut_col = QtWidgets.QVBoxLayout()
        shortcut_col.setSpacing(2)
        shortcut_col.addLayout(shortcut_row)
        shortcut_hint = QtWidgets.QLabel("Click then press keys")
        shortcut_hint.setStyleSheet("color: #666; font-size: 11px;")
        shortcut_col.addWidget(shortcut_hint)

        form = QtWidgets.QFormLayout()
        form.addRow("Result style", self.result_style)
        form.addRow(self.allow_fuzzy)
        form.addRow(self.switch_wb)
        form.addRow("Open palette shortcut", shortcut_col)

        hint = QtWidgets.QLabel(
            "These settings are also available under "
            "Edit → Preferences → ToolSeek. "
            "A shortcut already used elsewhere is rejected as soon as "
            "you press it."
        )
        hint.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QtWidgets.QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(hint)
        root.addWidget(buttons)

        self._load()

    def _reset_shortcut_field(self) -> None:
        set_recorded_shortcut(
            self.open_shortcut, prefs.DEFAULT_OPEN_SHORTCUT, validate=True
        )

    def _load(self) -> None:
        style = prefs.result_style()
        index = self.result_style.findData(style)
        self.result_style.setCurrentIndex(max(0, index))
        self.allow_fuzzy.setChecked(prefs.allow_fuzzy())
        self.switch_wb.setChecked(prefs.switch_workbench())
        set_recorded_shortcut(self.open_shortcut, prefs.open_shortcut())

    def apply(self) -> None:
        style = self.result_style.currentData() or "icons"
        prefs.set_result_style(str(style))
        prefs.set_allow_fuzzy(self.allow_fuzzy.isChecked())
        prefs.set_switch_workbench(self.switch_wb.isChecked())

        from . import bootstrap

        desired = recorded_shortcut_text(self.open_shortcut) or prefs.DEFAULT_OPEN_SHORTCUT
        if not bootstrap.try_set_open_shortcut(desired, interactive=True):
            # Conflict: other prefs already saved; restore field to active binding.
            set_recorded_shortcut(self.open_shortcut, prefs.open_shortcut())


def open_preferences_dialog() -> None:
    from FreeCADGui import getMainWindow

    dialog = PreferencesDialog(getMainWindow())
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        dialog.apply()
