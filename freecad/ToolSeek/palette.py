# SPDX-License-Identifier: LGPL-2.1-or-later
"""Floating command search palette."""

from __future__ import annotations

from typing import Optional

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtGui, QtWidgets  # type: ignore
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
    except ImportError:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from .indexer import CommandInfo, build
from .matcher import filter_commands
from . import prefs

# Qt5 / Qt6 compatibility helpers
_Qt = QtCore.Qt


def _qt_attr(*names):
    for name in names:
        if hasattr(_Qt, name):
            return getattr(_Qt, name)
        # Nested enums (Qt6): WindowType.Tool, Key.Key_Escape, etc.
        parts = name.split(".")
        obj = _Qt
        ok = True
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                ok = False
                break
        if ok:
            return obj
    raise AttributeError(names[0])


_Tool = _qt_attr("Tool", "WindowType.Tool")
_Frameless = _qt_attr("FramelessWindowHint", "WindowType.FramelessWindowHint")
_Key_Escape = _qt_attr("Key_Escape", "Key.Key_Escape")
_Key_Up = _qt_attr("Key_Up", "Key.Key_Up")
_Key_Down = _qt_attr("Key_Down", "Key.Key_Down")
_ScrollBarAlwaysOff = _qt_attr("ScrollBarAlwaysOff", "ScrollBarPolicy.ScrollBarAlwaysOff")
_OtherFocusReason = _qt_attr("OtherFocusReason", "FocusReason.OtherFocusReason")
_UserRole = _qt_attr("UserRole", "ItemDataRole.UserRole")
_AlignRight = _qt_attr("AlignRight", "AlignmentFlag.AlignRight")
_AlignVCenter = _qt_attr("AlignVCenter", "AlignmentFlag.AlignVCenter")

_WindowDeactivate = getattr(
    QtCore.QEvent,
    "WindowDeactivate",
    getattr(getattr(QtCore.QEvent, "Type", object), "WindowDeactivate", 24),
)
_KeyPress = getattr(
    QtCore.QEvent,
    "KeyPress",
    getattr(getattr(QtCore.QEvent, "Type", object), "KeyPress", 6),
)

_ROLE_NAME = _UserRole
_ROLE_ACTIVE = _UserRole + 1
_ROLE_WORKBENCH = _UserRole + 2
_ROLE_CURRENT_WB = _UserRole + 3

_FILTER_CURRENT = "__current__"
_FILTER_ALL = "__all__"

# Inactive: plain grey. Other workbench: muted slate (still selectable).
_INACTIVE_FG = QtGui.QColor(128, 128, 128)
_OTHER_WB_FG = QtGui.QColor(95, 115, 140)

_palette_ref: Optional["CommandPalette"] = None


class _SearchLineEdit(QtWidgets.QLineEdit):
    """Line edit that forwards Up/Down/Esc to the palette."""

    navigate = QtCore.Signal(object)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (_Key_Up, _Key_Down, _Key_Escape):
            self.navigate.emit(key)
            event.accept()
            return
        super().keyPressEvent(event)


class _ResultRow(QtWidgets.QWidget):
    """Label on the left, keyboard shortcut right-aligned."""

    def __init__(
        self,
        label: str,
        shortcut: str = "",
        icon=None,
        *,
        show_icon: bool = True,
        foreground: QtGui.QColor | None = None,
        parent=None,
    ):
        super().__init__(parent)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(6, 2, 8, 2)
        row.setSpacing(8)

        self._icon = QtWidgets.QLabel()
        self._icon.setFixedSize(20, 20)
        if show_icon and icon is not None:
            pix = icon.pixmap(20, 20) if hasattr(icon, "pixmap") else None
            if pix is not None and not pix.isNull():
                self._icon.setPixmap(pix)
            else:
                self._icon.setFixedSize(0, 0)
        else:
            self._icon.setFixedSize(0, 0)
        row.addWidget(self._icon)

        self._label = QtWidgets.QLabel(label)
        if foreground is not None:
            self._label.setStyleSheet(
                f"color: {foreground.name()}; font-size: 13px;"
            )
        row.addWidget(self._label, 1)

        self._shortcut = QtWidgets.QLabel(shortcut or "")
        self._shortcut.setAlignment(_AlignRight | _AlignVCenter)
        self._shortcut.setStyleSheet("color: #8c8c8c; font-size: 12px;")
        if not shortcut:
            self._shortcut.hide()
        row.addWidget(self._shortcut)


class CommandPalette(QtWidgets.QDialog):
    MIN_WIDTH = 560
    MIN_HEIGHT = 360
    MAX_VISIBLE = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolSeekPalette")
        self.setWindowTitle("ToolSeek")
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setWindowFlags(_Tool | _Frameless)
        self.setModal(False)

        self._commands: list[CommandInfo] = []
        self._show_icons = True
        self._allow_fuzzy = True
        self._switch_workbench = True

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setSpacing(8)
        filter_label = QtWidgets.QLabel("Workbench")
        filter_label.setStyleSheet("color: #aaa; font-size: 12px;")
        filter_row.addWidget(filter_label)

        self.wb_filter = QtWidgets.QComboBox()
        self.wb_filter.setMinimumWidth(180)
        self.wb_filter.setToolTip("Limit results to a workbench")
        filter_row.addWidget(self.wb_filter, 1)
        layout.addLayout(filter_row)

        self.search = _SearchLineEdit()
        self.search.setPlaceholderText("Type a command name…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.list = QtWidgets.QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(_ScrollBarAlwaysOff)
        self.list.setIconSize(QtCore.QSize(20, 20))
        layout.addWidget(self.list)

        self.hint = QtWidgets.QLabel(
            "↑↓ navigate  ·  Enter run  ·  Esc close  ·  other workbench shown muted"
        )
        self.hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.hint)

        self.wb_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.search.textChanged.connect(self._on_text_changed)
        self.search.returnPressed.connect(self._run_current)
        self.search.navigate.connect(self._on_navigate)
        self.list.itemActivated.connect(self._on_item_activated)
        self.list.itemClicked.connect(self._on_item_activated)

        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        etype = event.type()
        if obj is self and etype == _WindowDeactivate:
            self.close()
            return True
        if etype == _KeyPress and event.key() == _Key_Escape:
            self.close()
            return True
        return super().eventFilter(obj, event)

    def _reload_prefs(self):
        try:
            self._show_icons = prefs.show_icons()
            self._allow_fuzzy = prefs.allow_fuzzy()
            self._switch_workbench = prefs.switch_workbench()
        except Exception:
            self._show_icons = True
            self._allow_fuzzy = True
            self._switch_workbench = True

    def open_palette(self):
        self._reload_prefs()
        self._commands = build()
        self._rebuild_workbench_filter()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._populate(self.search.text())
        self._center_on_main_window()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus(_OtherFocusReason)

    def _center_on_main_window(self):
        mw = Gui.getMainWindow()
        if mw is None:
            return
        geo = mw.geometry()
        x = geo.x() + (geo.width() - self.MIN_WIDTH) // 2
        y = geo.y() + max(40, (geo.height() - self.MIN_HEIGHT) // 4)
        self.setGeometry(x, y, self.MIN_WIDTH, self.MIN_HEIGHT)

    def _rebuild_workbench_filter(self):
        """Populate All / Current / each workbench present in the index."""
        names: dict[str, str] = {}
        has_current = False
        for cmd in self._commands:
            if cmd.current_workbench:
                has_current = True
            key = cmd.workbench_id or cmd.workbench_name
            label = cmd.workbench_name or cmd.workbench_id
            if key and label:
                names[key] = label

        previous = self.wb_filter.currentData()
        self.wb_filter.blockSignals(True)
        self.wb_filter.clear()
        self.wb_filter.addItem("Current workbench", _FILTER_CURRENT)
        self.wb_filter.addItem("All workbenches", _FILTER_ALL)
        for key in sorted(names, key=lambda k: names[k].casefold()):
            self.wb_filter.addItem(names[key], key)

        # Default: Current when we know the active bench; otherwise All.
        target = previous
        if target is None:
            target = _FILTER_CURRENT if has_current else _FILTER_ALL
        idx = self.wb_filter.findData(target)
        if idx < 0:
            idx = 0 if has_current else 1
        self.wb_filter.setCurrentIndex(idx)
        self.wb_filter.blockSignals(False)

    def _filter_mode(self):
        return self.wb_filter.currentData()

    def _apply_workbench_filter(
        self, commands: list[CommandInfo]
    ) -> list[CommandInfo]:
        mode = self._filter_mode()
        if mode is None or mode == _FILTER_ALL:
            return commands
        if mode == _FILTER_CURRENT:
            current = [c for c in commands if c.current_workbench]
            return current if current else commands
        return [
            c
            for c in commands
            if c.workbench_id == mode or c.workbench_name == mode
        ]

    def _item_label(self, cmd: CommandInfo, show_wb: bool) -> str:
        # Primary text is always the user-facing menu label.
        parts = [cmd.menu_text or cmd.name]
        if show_wb and not cmd.current_workbench and cmd.workbench_name:
            parts.append(f"·  {cmd.workbench_name}")
        return "  ".join(parts)

    def _populate(self, query: str):
        scoped = self._apply_workbench_filter(self._commands)
        matched = filter_commands(
            query, scoped, allow_fuzzy=self._allow_fuzzy
        )
        if len(matched) > self.MAX_VISIBLE:
            matched = matched[: self.MAX_VISIBLE]

        show_wb = self._filter_mode() == _FILTER_ALL

        self.list.clear()
        for cmd in matched:
            label = self._item_label(cmd, show_wb)
            item = QtWidgets.QListWidgetItem()
            item.setData(_ROLE_NAME, cmd.name)
            item.setData(_ROLE_ACTIVE, cmd.active)
            item.setData(_ROLE_WORKBENCH, cmd.workbench_id)
            item.setData(_ROLE_CURRENT_WB, cmd.current_workbench)
            tip_parts = [cmd.menu_text or cmd.name, cmd.name]
            if cmd.workbench_name:
                tip_parts.append(f"Workbench: {cmd.workbench_name}")
            if cmd.shortcut:
                tip_parts.append(f"Shortcut: {cmd.shortcut}")
            if cmd.tooltip:
                tip_parts.append(cmd.tooltip)
            item.setToolTip("\n".join(tip_parts))

            fg = None
            if not cmd.active:
                fg = _INACTIVE_FG
            elif not cmd.current_workbench and cmd.workbench_name:
                fg = _OTHER_WB_FG

            row = _ResultRow(
                label,
                cmd.shortcut or "",
                cmd.icon if self._show_icons else None,
                show_icon=self._show_icons,
                foreground=fg,
            )
            hint = row.sizeHint()
            if hint.height() < 24:
                hint.setHeight(28)
            if hint.width() < 100:
                hint.setWidth(self.list.viewport().width() or self.MIN_WIDTH)
            item.setSizeHint(hint)
            self.list.addItem(item)
            self.list.setItemWidget(item, row)

        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _on_filter_changed(self, _index: int = 0):
        self._populate(self.search.text())

    def _on_text_changed(self, text: str):
        self._populate(text)

    def _on_navigate(self, key):
        if key == _Key_Escape:
            self.close()
            return
        count = self.list.count()
        if count == 0:
            return
        row = self.list.currentRow()
        if key == _Key_Down:
            self.list.setCurrentRow((row + 1) % count)
        elif key == _Key_Up:
            self.list.setCurrentRow((row - 1) % count)

    def _on_item_activated(self, item):
        if item is None:
            return
        self._run_command(
            item.data(_ROLE_NAME),
            item.data(_ROLE_WORKBENCH) or "",
            bool(item.data(_ROLE_CURRENT_WB)),
        )

    def _run_current(self):
        item = self.list.currentItem()
        if item is None:
            return
        self._run_command(
            item.data(_ROLE_NAME),
            item.data(_ROLE_WORKBENCH) or "",
            bool(item.data(_ROLE_CURRENT_WB)),
        )

    def _run_command(
        self,
        name: Optional[str],
        workbench_id: str = "",
        current_workbench: bool = True,
    ):
        if not name:
            return
        self.close()

        if (
            self._switch_workbench
            and workbench_id
            and not current_workbench
        ):
            try:
                Gui.activateWorkbench(workbench_id)
            except Exception as exc:
                App.Console.PrintError(
                    f"ToolSeek: could not activate workbench '{workbench_id}' "
                    f"before '{name}': {exc}\n"
                )

        try:
            Gui.runCommand(name)
        except Exception as exc:
            App.Console.PrintError(f"ToolSeek: failed to run '{name}': {exc}\n")


def show_palette():
    """Show the command palette. Pressing the hotkey again while open closes it."""
    global _palette_ref
    mw = Gui.getMainWindow()
    if _palette_ref is None:
        _palette_ref = CommandPalette(mw)
    elif _palette_ref.isVisible():
        _palette_ref.close()
        return
    _palette_ref.open_palette()
