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


class PreferencesDialog(QtWidgets.QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ToolSeek")
        self.setModal(True)
        self.resize(440, 220)

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

        form = QtWidgets.QFormLayout()
        form.addRow("Result style", self.result_style)
        form.addRow(self.allow_fuzzy)
        form.addRow(self.switch_wb)

        hint = QtWidgets.QLabel(
            "These settings are also available under "
            "Edit → Preferences → ToolSeek."
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

    def _load(self) -> None:
        style = prefs.result_style()
        index = self.result_style.findData(style)
        self.result_style.setCurrentIndex(max(0, index))
        self.allow_fuzzy.setChecked(prefs.allow_fuzzy())
        self.switch_wb.setChecked(prefs.switch_workbench())

    def apply(self) -> None:
        style = self.result_style.currentData() or "icons"
        prefs.set_result_style(str(style))
        prefs.set_allow_fuzzy(self.allow_fuzzy.isChecked())
        prefs.set_switch_workbench(self.switch_wb.isChecked())


def open_preferences_dialog() -> None:
    from FreeCADGui import getMainWindow

    dialog = PreferencesDialog(getMainWindow())
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        dialog.apply()
