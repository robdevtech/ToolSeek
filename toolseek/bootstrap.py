# SPDX-License-Identifier: LGPL-2.1-or-later
"""Install Tools menu entries + Ctrl+Space QShortcut on the FreeCAD main window.

FreeCAD's Gui.appendMenu / Accel from GetResources are unreliable for InitGui-only
mods (items often never appear under Tools — NeoRibbon has the same gap). We:
  1. Register the commands
  2. Directly add QActions under the live Tools QMenu
  3. Re-add those actions whenever Tools is about to show (survives rebuilds)
  4. Install an ApplicationShortcut QShortcut for Ctrl+Space
  5. Register Edit → Preferences → ToolSeek

Note: FreeCAD 1.1 Flatpak uses PySide6. QAction and QShortcut live in QtGui
(not QtWidgets) under Qt6.
"""

from __future__ import annotations

import os

import FreeCAD as App
import FreeCADGui as Gui

from .command import (
    COMMAND_OPEN,
    COMMAND_PREFERENCES,
    register as register_command,
)

try:
    from PySide import QtCore, QtGui, QtWidgets  # type: ignore
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
    except ImportError:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

try:
    import shiboken6 as shiboken  # type: ignore
except ImportError:
    try:
        import shiboken2 as shiboken  # type: ignore
    except ImportError:
        try:
            import shiboken  # type: ignore
        except ImportError:
            shiboken = None  # type: ignore

# Qt6 moved these from QtWidgets → QtGui; Qt5 still has them on QtWidgets.
QAction = getattr(QtGui, "QAction", None) or getattr(QtWidgets, "QAction")
QShortcut = getattr(QtGui, "QShortcut", None) or getattr(QtWidgets, "QShortcut")

_SHORTCUT_OBJECT_NAME = "ToolSeek_CtrlSpaceShortcut"
_ACTION_OBJECT_NAME = "ToolSeek_ToolsAction"
_PREFS_ACTION_OBJECT_NAME = "ToolSeek_PrefsAction"
_DEFAULT_SHORTCUT = "Ctrl+Space"

_installed = False
_reapply_pending = False
_tools_about_to_show_hooked = False
_menu_fail_logged = False
_foreign_shortcut_cleared = False


def _qt_attr(*names):
    root = QtCore.Qt
    for name in names:
        if hasattr(root, name):
            return getattr(root, name)
        parts = name.split(".")
        obj = root
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


_ApplicationShortcut = _qt_attr(
    "ApplicationShortcut", "ShortcutContext.ApplicationShortcut"
)


def _alive(obj) -> bool:
    if obj is None:
        return False
    if shiboken is None:
        return True
    try:
        return bool(shiboken.isValid(obj))
    except Exception:
        return False


def _main_window():
    try:
        mw = Gui.getMainWindow()
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintError(f"ToolSeek: getMainWindow failed: {exc}\n")
        return None
    return mw if _alive(mw) else None


def _norm(text: str) -> str:
    return (text or "").replace("&", "").strip().lower()


def _resources_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "resources",
    )


def _register_preference_page() -> None:
    resources = _resources_dir()
    icons = os.path.join(resources, "icons")
    ui = os.path.join(resources, "ui", "preferences.ui")
    if not os.path.isfile(ui):
        App.Console.PrintWarning(f"ToolSeek: preference UI missing: {ui}\n")
        return

    # FreeCAD looks up "preferences-<group>" (lowercase) via icon paths.
    try:
        if hasattr(Gui, "addIconPath") and os.path.isdir(icons):
            Gui.addIconPath(icons)
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(
            f"ToolSeek: preference icon path registration failed: {exc}\n"
        )

    try:
        Gui.addPreferencePage(ui, "ToolSeek")
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(f"ToolSeek: addPreferencePage failed: {exc}\n")


def _find_tools_menu(mw):
    """Return the live Tools QMenu from the main menu bar action text only."""
    if not _alive(mw):
        return None
    mb = mw.menuBar()
    if not _alive(mb):
        return None
    try:
        actions = list(mb.actions())
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(f"ToolSeek: menuBar.actions failed: {exc}\n")
        return None
    for action in actions:
        if not _alive(action):
            continue
        try:
            if _norm(action.text()) != "tools":
                continue
            menu = action.menu()
        except Exception:
            continue
        if _alive(menu):
            return menu
    return None


def _run_open_command():
    try:
        Gui.runCommand(COMMAND_OPEN)
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintError(
            f"ToolSeek: runCommand({COMMAND_OPEN}) failed: {exc}\n"
        )


def _run_prefs_command():
    try:
        Gui.runCommand(COMMAND_PREFERENCES)
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintError(
            f"ToolSeek: runCommand({COMMAND_PREFERENCES}) failed: {exc}\n"
        )


def _action_present(tools, object_name: str, *text_prefixes: str) -> bool:
    try:
        for action in list(tools.actions()):
            if not _alive(action):
                continue
            if action.objectName() == object_name:
                return True
            text = _norm(action.text())
            for prefix in text_prefixes:
                if text.startswith(prefix):
                    try:
                        action.setObjectName(object_name)
                    except Exception:
                        pass
                    return True
    except Exception:
        # Common during FreeCAD startup while menus are rebuilt.
        return False
    return False


def _insert_before_customize(tools, action) -> None:
    customize = None
    for candidate in list(tools.actions()):
        if not _alive(candidate):
            continue
        if _norm(candidate.text()).startswith("customize"):
            customize = candidate
            break
    if customize is not None and _alive(customize):
        tools.insertAction(customize, action)
    else:
        tools.addAction(action)


def _ensure_tools_action(mw) -> bool:
    """Add ToolSeek… / preferences under Tools via Qt (survives appendMenu loss)."""
    global _menu_fail_logged
    tools = _find_tools_menu(mw)
    if tools is None:
        return False

    added_open = False
    added_prefs = False

    try:
        if not _action_present(
            tools, _ACTION_OBJECT_NAME, "toolseek…", "toolseek —", "command search"
        ):
            action = QAction("ToolSeek…", tools)
            action.setObjectName(_ACTION_OBJECT_NAME)
            action.setToolTip(
                "Search and run FreeCAD commands by typing (Ctrl+Space)"
            )
            # Shortcut is owned by QShortcut below — do not setShortcut on the action.
            action.triggered.connect(_run_open_command)
            _insert_before_customize(tools, action)
            added_open = True

        if not _action_present(
            tools, _PREFS_ACTION_OBJECT_NAME, "toolseek preferences"
        ):
            prefs_action = QAction("ToolSeek preferences…", tools)
            prefs_action.setObjectName(_PREFS_ACTION_OBJECT_NAME)
            prefs_action.setToolTip("Open ToolSeek settings")
            prefs_action.triggered.connect(_run_prefs_command)
            _insert_before_customize(tools, prefs_action)
            added_prefs = True
    except Exception as exc:  # noqa: BLE001
        if not _menu_fail_logged:
            _menu_fail_logged = True
            App.Console.PrintWarning(
                f"ToolSeek: Tools menu not writable yet ({exc}); "
                "will retry on Tools aboutToShow\n"
            )
        return False

    if added_open:
        App.Console.PrintMessage("ToolSeek: added Tools → ToolSeek…\n")
    if added_prefs:
        App.Console.PrintMessage(
            "ToolSeek: added Tools → ToolSeek preferences…\n"
        )
    return True


def _hook_tools_about_to_show(mw) -> None:
    """Re-inject the menu item every time Tools opens (handles menu rebuilds)."""
    global _tools_about_to_show_hooked
    tools = _find_tools_menu(mw)
    if tools is None:
        return
    if _tools_about_to_show_hooked:
        # Menu object may have been replaced; reconnect if needed.
        try:
            tools.aboutToShow.disconnect(_on_tools_about_to_show)
        except Exception:
            pass
    try:
        tools.aboutToShow.connect(_on_tools_about_to_show)
        _tools_about_to_show_hooked = True
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(
            f"ToolSeek: Tools.aboutToShow hook failed: {exc}\n"
        )


def _on_tools_about_to_show():
    mw = _main_window()
    if mw is None:
        return
    _ensure_tools_action(mw)


def _clear_foreign_ctrl_space(mw) -> None:
    """Remove unnamed Ctrl+Space shortcuts so ours is the only binder."""
    global _foreign_shortcut_cleared
    if not _alive(mw):
        return
    try:
        shortcuts = list(mw.findChildren(QShortcut))
    except Exception:
        return
    target = QtGui.QKeySequence(_DEFAULT_SHORTCUT).toString()
    removed = False
    for sc in shortcuts:
        if not _alive(sc):
            continue
        try:
            name = sc.objectName() or ""
            if name == _SHORTCUT_OBJECT_NAME:
                continue
            # Drop legacy FC_Search binder or any other Ctrl+Space shortcut.
            if name == "FCSearch_CtrlSpaceShortcut" or sc.key().toString() == target:
                sc.setEnabled(False)
                sc.deleteLater()
                removed = True
                continue
        except Exception:
            continue
    if removed and not _foreign_shortcut_cleared:
        _foreign_shortcut_cleared = True
        App.Console.PrintMessage(
            "ToolSeek: removed duplicate Ctrl+Space shortcut\n"
        )


def _ensure_shortcut(mw) -> bool:
    """Install Ctrl+Space on the main window (independent of Accel/menu)."""
    if not _alive(mw):
        return False

    _clear_foreign_ctrl_space(mw)

    try:
        existing = mw.findChild(QShortcut, _SHORTCUT_OBJECT_NAME)
    except Exception:
        existing = None
    if existing is not None and _alive(existing):
        return True

    try:
        sequence = QtGui.QKeySequence(_DEFAULT_SHORTCUT)
        shortcut = QShortcut(sequence, mw)
        shortcut.setObjectName(_SHORTCUT_OBJECT_NAME)
        shortcut.setContext(_ApplicationShortcut)
        shortcut.setAutoRepeat(False)
        shortcut.activated.connect(_run_open_command)
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintError(f"ToolSeek: QShortcut install failed: {exc}\n")
        return False

    App.Console.PrintMessage(
        f"ToolSeek: installed {_DEFAULT_SHORTCUT} shortcut\n"
    )
    return True


def _apply_ui():
    mw = _main_window()
    if mw is None:
        return
    _ensure_tools_action(mw)
    _hook_tools_about_to_show(mw)
    if not _ensure_shortcut(mw):
        App.Console.PrintWarning(
            "ToolSeek: shortcut not ready yet; will retry\n"
        )


def _schedule_reapply(delay_ms: int = 0):
    """Queue a UI re-apply. Coalesce only identical immediate (0ms) requests."""
    global _reapply_pending
    if delay_ms == 0:
        if _reapply_pending:
            return
        _reapply_pending = True

    def _run():
        global _reapply_pending
        if delay_ms == 0:
            _reapply_pending = False
        try:
            _apply_ui()
        except Exception as exc:  # noqa: BLE001
            App.Console.PrintError(f"ToolSeek: UI apply failed: {exc}\n")

    QtCore.QTimer.singleShot(delay_ms, _run)


def _on_workbench_activated(_name: str = ""):
    _schedule_reapply(0)
    _schedule_reapply(300)


def install() -> None:
    """Called once from InitGui.py."""
    global _installed
    if _installed:
        return
    _installed = True

    try:
        register_command()
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintError(f"ToolSeek: addCommand failed: {exc}\n")
        raise

    _register_preference_page()

    # Keep FreeCAD's menu model aware of the commands (Customize Keyboard).
    # This alone does NOT reliably show the item under Tools for InitGui mods.
    try:
        append = getattr(Gui, "appendMenu", None)
        if callable(append):
            append("Tools", [COMMAND_OPEN, COMMAND_PREFERENCES])
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(f"ToolSeek: Gui.appendMenu failed: {exc}\n")

    mw = _main_window()
    if mw is not None:
        try:
            mw.workbenchActivated.connect(_on_workbench_activated)
        except Exception as exc:  # noqa: BLE001
            App.Console.PrintWarning(
                f"ToolSeek: could not connect workbenchActivated: {exc}\n"
            )

    # InitGui runs while menus are still being built; retry across startup.
    for delay in (0, 400, 1200, 3000):
        _schedule_reapply(delay)

    App.Console.PrintMessage("ToolSeek: loaded (Ctrl+Space)\n")
