# SPDX-License-Identifier: LGPL-2.1-or-later
"""Install Tools menu entries + open-palette QShortcut on the FreeCAD main window.

FreeCAD's Gui.appendMenu / Accel from GetResources are unreliable for InitGui-only
mods (items often never appear under Tools — NeoRibbon has the same gap). We:
  1. Register the commands
  2. Directly add QActions under the live Tools QMenu
  3. Re-add those actions whenever Tools is about to show (survives rebuilds)
  4. Install an ApplicationShortcut QShortcut (default Ctrl+Space; user-configurable)
  5. Register Edit → Preferences → ToolSeek
  6. Reload the shortcut when Mod/ToolSeek preferences change

Note: FreeCAD 1.1 Flatpak uses PySide6. QAction and QShortcut live in QtGui
(not QtWidgets) under Qt6.
"""

from __future__ import annotations

import os

import FreeCAD as App
import FreeCADGui as Gui

from . import prefs
from .command import (
    COMMAND_OPEN,
    COMMAND_PREFERENCES,
    register as register_command,
)
from .shortcut_conflicts import (
    TOOLSEEK_SHORTCUT_OBJECT_NAMES,
    find_shortcut_conflicts,
    normalize_shortcut,
    sequences_match,
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

_SHORTCUT_OBJECT_NAME = "ToolSeek_OpenShortcut"
_ACTION_OBJECT_NAME = "ToolSeek_ToolsAction"
_PREFS_ACTION_OBJECT_NAME = "ToolSeek_PrefsAction"

_installed = False
_reapply_pending = False
_tools_about_to_show_hooked = False
_menu_fail_logged = False
_legacy_shortcut_cleared = False
_prefs_observer = None
_prefs_observer_attached = False
_ignore_pref_notify = False
_applied_shortcut = ""
_last_conflict_key = ""


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

    # Python page (loads .ui) so we can wire QKeySequenceEdit for recording.
    try:
        from .prefs_page import ToolSeekPreferencePage

        Gui.addPreferencePage(ToolSeekPreferencePage, "ToolSeek")
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(
            f"ToolSeek: Python preference page failed ({exc}); "
            "falling back to .ui file\n"
        )
        try:
            Gui.addPreferencePage(ui, "ToolSeek")
        except Exception as exc2:  # noqa: BLE001
            App.Console.PrintWarning(
                f"ToolSeek: addPreferencePage failed: {exc2}\n"
            )


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


def _open_shortcut_tip() -> str:
    sc = _applied_shortcut or prefs.open_shortcut()
    return f"Search and run FreeCAD commands by typing ({sc})"


def _update_tools_action_tip(mw) -> None:
    tools = _find_tools_menu(mw)
    if tools is None:
        return
    try:
        for action in list(tools.actions()):
            if not _alive(action):
                continue
            if action.objectName() == _ACTION_OBJECT_NAME:
                action.setToolTip(_open_shortcut_tip())
                return
    except Exception:
        return


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
            action.setToolTip(_open_shortcut_tip())
            # Shortcut is owned by QShortcut below — do not setShortcut on the action.
            action.triggered.connect(_run_open_command)
            _insert_before_customize(tools, action)
            added_open = True
        else:
            _update_tools_action_tip(mw)

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


def _find_toolseek_shortcut(mw):
    """Return our QShortcut if present (current or legacy object name)."""
    if not _alive(mw):
        return None
    for name in (_SHORTCUT_OBJECT_NAME, "ToolSeek_CtrlSpaceShortcut"):
        try:
            existing = mw.findChild(QShortcut, name)
        except Exception:
            existing = None
        if existing is not None and _alive(existing):
            try:
                if existing.objectName() != _SHORTCUT_OBJECT_NAME:
                    existing.setObjectName(_SHORTCUT_OBJECT_NAME)
            except Exception:
                pass
            return existing
    return None


def _clear_legacy_fcsearch_shortcut(mw) -> None:
    """Remove only the pre-ToolSeek binder; never wipe unrelated shortcuts."""
    global _legacy_shortcut_cleared
    if not _alive(mw):
        return
    try:
        shortcuts = list(mw.findChildren(QShortcut))
    except Exception:
        return
    removed = False
    for sc in shortcuts:
        if not _alive(sc):
            continue
        try:
            if (sc.objectName() or "") != "FCSearch_CtrlSpaceShortcut":
                continue
            sc.setEnabled(False)
            sc.deleteLater()
            removed = True
        except Exception:
            continue
    if removed and not _legacy_shortcut_cleared:
        _legacy_shortcut_cleared = True
        App.Console.PrintMessage(
            "ToolSeek: removed legacy FCSearch Ctrl+Space shortcut\n"
        )


def _clear_unnamed_shortcuts_for_sequence(mw, sequence: str) -> int:
    """Remove unnamed QShortcuts matching *sequence* (startup leftovers).

    FreeCAD / prior binders sometimes leave an unnamed Ctrl+Space QShortcut.
    Treating that as a hard conflict left ToolSeek with no binding at all.
    Named foreign shortcuts are left untouched.
    """
    target = normalize_shortcut(sequence)
    if not target or not _alive(mw):
        return 0
    try:
        shortcuts = list(mw.findChildren(QShortcut))
    except Exception:
        return 0
    removed = 0
    for sc in shortcuts:
        if not _alive(sc):
            continue
        try:
            name = (sc.objectName() or "").strip()
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
            sc.setEnabled(False)
            sc.deleteLater()
            removed += 1
        except Exception:
            continue
    return removed


def _conflict_detail(conflicts: list[str]) -> str:
    detail = "; ".join(conflicts[:8])
    if len(conflicts) > 8:
        detail += f"; …(+{len(conflicts) - 8} more)"
    return detail


def _warn_shortcut_conflict(
    sequence: str,
    conflicts: list[str],
    *,
    interactive: bool,
    kept_previous: bool,
) -> None:
    global _last_conflict_key
    # Startup retries would otherwise spam the same conflict warning.
    if not interactive and _last_conflict_key == sequence:
        return
    _last_conflict_key = sequence
    detail = _conflict_detail(conflicts)
    if kept_previous:
        App.Console.PrintWarning(
            f"ToolSeek: shortcut '{sequence}' conflicts with {detail}; "
            "keeping the previous ToolSeek shortcut (not overriding).\n"
        )
    else:
        App.Console.PrintWarning(
            f"ToolSeek: shortcut '{sequence}' also used by {detail}; "
            "installing ToolSeek binding anyway so the palette stays reachable.\n"
        )
    if not interactive:
        return
    mw = _main_window()
    lines = "\n".join(f"• {c}" for c in conflicts[:12])
    if len(conflicts) > 12:
        lines += f"\n• …and {len(conflicts) - 12} more"
    try:
        QtWidgets.QMessageBox.warning(
            mw,
            "ToolSeek",
            (
                f"Cannot bind shortcut “{sequence}”.\n\n"
                "It conflicts with an existing FreeCAD shortcut:\n"
                f"{lines}\n\n"
                "The previous ToolSeek shortcut was kept."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(
            f"ToolSeek: could not show shortcut conflict dialog: {exc}\n"
        )


def _desired_open_shortcut(value: str | None = None) -> str:
    raw = prefs.open_shortcut() if value is None else (value or "").strip()
    if not raw:
        raw = prefs.DEFAULT_OPEN_SHORTCUT
    normalized = normalize_shortcut(raw)
    return normalized or prefs.DEFAULT_OPEN_SHORTCUT


def try_set_open_shortcut(
    value: str,
    *,
    interactive: bool = False,
    persist: bool = True,
) -> bool:
    """Validate, optionally persist, and apply an open-palette shortcut.

    Returns False on conflict (existing FreeCAD binding left untouched; ToolSeek
    keeps its previously applied shortcut). ToolSeek's own QShortcut is excluded
    from conflict detection so rebinding / reloads are not false positives.
    """
    global _applied_shortcut, _ignore_pref_notify, _last_conflict_key

    desired = _desired_open_shortcut(value)
    mw = _main_window()
    if mw is None:
        if persist:
            prefs.set_open_shortcut(desired)
        return False

    _clear_legacy_fcsearch_shortcut(mw)
    existing = _find_toolseek_shortcut(mw)

    if existing is not None and sequences_match(existing.key(), desired):
        _applied_shortcut = desired
        if persist and normalize_shortcut(prefs.open_shortcut()) != desired:
            _ignore_pref_notify = True
            try:
                prefs.set_open_shortcut(desired)
            finally:
                _ignore_pref_notify = False
        _update_tools_action_tip(mw)
        return True

    # Unnamed Ctrl+Space (etc.) leftovers must not block first install.
    cleared = _clear_unnamed_shortcuts_for_sequence(mw, desired)
    if cleared:
        App.Console.PrintMessage(
            f"ToolSeek: cleared {cleared} unnamed '{desired}' shortcut(s)\n"
        )

    try:
        conflicts = find_shortcut_conflicts(mw, desired)
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(
            f"ToolSeek: shortcut conflict scan failed ({exc}); "
            "continuing with install\n"
        )
        conflicts = []
    # Belt-and-suspenders: drop any leftover labels that still name our binder.
    conflicts = [
        c
        for c in conflicts
        if not any(n in c for n in TOOLSEEK_SHORTCUT_OBJECT_NAMES)
    ]
    if conflicts:
        if interactive or existing is not None:
            # Interactive prefs / rebind: never override a foreign binding.
            # If we already own a binder, keep it rather than switching.
            _warn_shortcut_conflict(
                desired,
                conflicts,
                interactive=interactive,
                kept_previous=True,
            )
            return False
        # Startup with no ToolSeek binder yet: still install so the palette
        # remains reachable; user can change the chord in preferences.
        _warn_shortcut_conflict(
            desired,
            conflicts,
            interactive=False,
            kept_previous=False,
        )

    try:
        sequence = QtGui.QKeySequence(desired)
        if existing is not None and _alive(existing):
            existing.setKey(sequence)
            created = False
        else:
            shortcut = QShortcut(sequence, mw)
            shortcut.setObjectName(_SHORTCUT_OBJECT_NAME)
            shortcut.setContext(_ApplicationShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(_run_open_command)
            created = True
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintError(f"ToolSeek: QShortcut install failed: {exc}\n")
        return False

    _last_conflict_key = ""
    _applied_shortcut = desired
    if persist:
        _ignore_pref_notify = True
        try:
            prefs.set_open_shortcut(desired)
        finally:
            _ignore_pref_notify = False

    _update_tools_action_tip(mw)
    verb = "installed" if created else "updated"
    App.Console.PrintMessage(f"ToolSeek: {verb} {desired} shortcut\n")
    return True


def reload_open_shortcut(*, interactive: bool = False) -> bool:
    """Re-read OpenShortcut from preferences and apply it."""
    return try_set_open_shortcut(
        prefs.open_shortcut(),
        interactive=interactive,
        persist=False,
    )


def _ensure_shortcut(mw) -> bool:
    """Install or refresh the open-palette shortcut from preferences.

    Returns True when a ToolSeek shortcut is bound afterward (newly applied or
    previous binding kept after a conflict).
    """
    if not _alive(mw):
        return False
    try_set_open_shortcut(
        prefs.open_shortcut(),
        interactive=False,
        persist=False,
    )
    return _find_toolseek_shortcut(mw) is not None


def _revert_open_shortcut_pref(previous: str) -> None:
    global _ignore_pref_notify
    text = previous or prefs.DEFAULT_OPEN_SHORTCUT
    _ignore_pref_notify = True
    try:
        prefs.set_open_shortcut(text)
    finally:
        _ignore_pref_notify = False


class _PrefsObserver:
    """Reload UI-bound settings when Edit → Preferences saves Mod/ToolSeek."""

    def slotParamChanged(self, _group, _tp, name, _value):
        if _ignore_pref_notify:
            return
        if name != prefs.PREF_OPEN_SHORTCUT:
            return
        previous = _applied_shortcut or prefs.DEFAULT_OPEN_SHORTCUT
        if reload_open_shortcut(interactive=True):
            return
        # Pref page already wrote the colliding value — roll it back.
        _revert_open_shortcut_pref(previous)

    def OnChange(self, _group, reason):
        # Classic ParameterGrp.Attach observer API.
        if reason == prefs.PREF_OPEN_SHORTCUT:
            self.slotParamChanged(_group, None, reason, None)


def _attach_prefs_observer() -> None:
    global _prefs_observer, _prefs_observer_attached
    if _prefs_observer_attached:
        return
    group = prefs.param_group()
    observer = _PrefsObserver()
    attached = False
    try:
        if hasattr(group, "AttachManager"):
            group.AttachManager(observer)
            attached = True
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(
            f"ToolSeek: AttachManager failed ({exc}); trying Attach\n"
        )
    if not attached:
        try:
            group.Attach(observer)
            attached = True
        except Exception as exc:  # noqa: BLE001
            App.Console.PrintWarning(
                f"ToolSeek: preference observer attach failed: {exc}\n"
            )
            return
    _prefs_observer = observer  # keep alive
    _prefs_observer_attached = True


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
    _attach_prefs_observer()

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

    App.Console.PrintMessage(
        f"ToolSeek: loaded ({prefs.open_shortcut()})\n"
    )
