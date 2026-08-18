# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offline checks for shortcut conflict skip rules (no FreeCAD / Qt runtime)."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeKeySequence:
    class SequenceFormat:
        PortableText = 0

    PortableText = 1

    def __init__(self, raw=""):
        self._raw = str(raw) if raw is not None else ""

    def toString(self, *args, **kwargs):
        return self._raw

    def isEmpty(self):
        return not self._raw.strip()


def _install_stubs() -> None:
    qtgui = types.SimpleNamespace(
        QKeySequence=_FakeKeySequence,
        QAction=type("QAction", (), {}),
        QShortcut=type("QShortcut", (), {}),
    )
    qtwidgets = types.SimpleNamespace(
        QAction=qtgui.QAction,
        QShortcut=qtgui.QShortcut,
    )
    pyside = types.ModuleType("PySide")
    pyside.QtGui = qtgui
    pyside.QtWidgets = qtwidgets
    sys.modules.setdefault("PySide", pyside)
    sys.modules.setdefault("PySide.QtGui", qtgui)
    sys.modules.setdefault("PySide.QtWidgets", qtwidgets)
    sys.modules.setdefault("FreeCADGui", MagicMock())
    sys.modules.setdefault("FreeCAD", MagicMock())


_install_stubs()

from freecad.ToolSeek.shortcut_conflicts import (  # noqa: E402
    clear_unnamed_shortcuts_for_sequence,
    find_shortcut_conflicts,
    is_toolseek_owned_name,
    qaction_should_skip,
    qshortcut_should_skip,
)


class _FakeQt:
    def __init__(
        self,
        *,
        name="",
        parent=None,
        enabled=True,
        key="",
        text="",
        shortcuts=None,
    ):
        self._name = name
        self._parent = parent
        self._enabled = enabled
        self._key = key
        self._text = text
        self._shortcuts = shortcuts
        self.deleted = False

    def objectName(self):
        return self._name

    def parent(self):
        return self._parent

    def isEnabled(self):
        return self._enabled

    def setEnabled(self, value):
        self._enabled = bool(value)

    def deleteLater(self):
        self.deleted = True

    def key(self):
        return self._key

    def text(self):
        return self._text

    def shortcuts(self):
        if self._shortcuts is not None:
            return list(self._shortcuts)
        return [self._key] if self._key else []

    def shortcut(self):
        return self._key


class _FakeMW:
    def __init__(self, shortcuts=(), actions=()):
        self.shortcuts = list(shortcuts)
        self.actions = list(actions)

    def findChildren(self, typ):
        name = getattr(typ, "__name__", "")
        if name == "QShortcut":
            return list(self.shortcuts)
        return list(self.actions)


class _FakeCmd:
    def __init__(self, accel: str):
        self._accel = accel

    def getInfo(self):
        return {"accel": self._accel}

    def getShortcut(self):
        return self._accel


class OwnedNameTests(unittest.TestCase):
    def test_current_and_legacy_binder_names(self):
        self.assertTrue(is_toolseek_owned_name("ToolSeek_OpenShortcut"))
        self.assertTrue(is_toolseek_owned_name("ToolSeek_CtrlSpaceShortcut"))
        self.assertTrue(is_toolseek_owned_name("FCSearch_CtrlSpaceShortcut"))
        self.assertTrue(is_toolseek_owned_name("ToolSeek_Open"))
        self.assertTrue(is_toolseek_owned_name("ToolSeek_ToolsAction"))
        self.assertFalse(is_toolseek_owned_name(""))
        self.assertFalse(is_toolseek_owned_name("Std_New"))


class SkipRuleTests(unittest.TestCase):
    def test_unnamed_leftover_is_skipped(self):
        sc = _FakeQt(name="", key="Ctrl+Space")
        self.assertTrue(qshortcut_should_skip(sc))

    def test_own_binder_is_skipped(self):
        sc = _FakeQt(name="ToolSeek_OpenShortcut", key="Ctrl+Space")
        self.assertTrue(qshortcut_should_skip(sc))

    def test_recorder_child_is_skipped(self):
        recorder = _FakeQt(name="ToolSeek_ShortcutRecorder")
        child = _FakeQt(name="internal", parent=recorder, key="Ctrl+Space")
        self.assertTrue(qshortcut_should_skip(child))

    def test_ignore_objects_skips_descendant(self):
        recorder = _FakeQt(name="prefsEdit")
        child = _FakeQt(name="foreignLooking", parent=recorder, key="Ctrl+Space")
        self.assertFalse(qshortcut_should_skip(child))
        self.assertTrue(qshortcut_should_skip(child, ignore_objects=(recorder,)))

    def test_named_foreign_shortcut_is_not_skipped(self):
        sc = _FakeQt(name="Std_SomeShortcut", key="Ctrl+Space")
        self.assertFalse(qshortcut_should_skip(sc))

    def test_toolseek_menu_action_is_skipped(self):
        action = _FakeQt(name="Std_Tool", text="ToolSeek…", key="Ctrl+Space")
        self.assertTrue(qaction_should_skip(action))
        foreign = _FakeQt(name="Std_New", text="New", key="Ctrl+N")
        self.assertFalse(qaction_should_skip(foreign))


class ConflictScanTests(unittest.TestCase):
    def setUp(self):
        import FreeCADGui as Gui

        self._gui = Gui
        self._old_list = getattr(Gui, "listCommands", None)
        self._old_command = getattr(Gui, "Command", None)
        Gui.listCommands = MagicMock(return_value=[])
        Gui.Command = MagicMock()
        Gui.Command.get = MagicMock(return_value=None)

    def tearDown(self):
        if self._old_list is not None:
            self._gui.listCommands = self._old_list
        if self._old_command is not None:
            self._gui.Command = self._old_command

    def test_reset_ctrl_space_ignores_own_binder_and_unnamed(self):
        own = _FakeQt(name="ToolSeek_OpenShortcut", key="Ctrl+Space")
        leftover = _FakeQt(name="", key="Ctrl+Space")
        mw = _FakeMW(shortcuts=(own, leftover))
        self.assertEqual(find_shortcut_conflicts(mw, "Ctrl+Space"), [])

    def test_named_foreign_shortcut_is_a_conflict(self):
        foreign = _FakeQt(name="OtherAddon_Open", key="Ctrl+Space")
        mw = _FakeMW(shortcuts=(foreign,))
        labels = find_shortcut_conflicts(mw, "Ctrl+Space")
        self.assertTrue(any("OtherAddon_Open" in label for label in labels))

    def test_real_command_conflict_is_reported(self):
        import FreeCADGui as Gui

        Gui.listCommands = MagicMock(return_value=["Std_New", "ToolSeek_Open"])
        Gui.Command.get = MagicMock(
            side_effect=lambda name: _FakeCmd("Ctrl+N")
            if name == "Std_New"
            else _FakeCmd("Ctrl+Space")
        )
        labels = find_shortcut_conflicts(_FakeMW(), "Ctrl+N")
        self.assertEqual(labels, ["Command: Std_New"])

    def test_clear_unnamed_leaves_named(self):
        leftover = _FakeQt(name="", key="Ctrl+Space")
        named = _FakeQt(name="OtherAddon_Open", key="Ctrl+Space")
        mw = _FakeMW(shortcuts=(leftover, named))
        removed = clear_unnamed_shortcuts_for_sequence(mw, "Ctrl+Space")
        self.assertEqual(removed, 1)
        self.assertTrue(leftover.deleted)
        self.assertFalse(leftover._enabled)
        self.assertFalse(named.deleted)


if __name__ == "__main__":
    unittest.main()
