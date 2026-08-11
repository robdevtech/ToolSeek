# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI smoke probe for ToolSeek. Run via FreeCAD with this file as argument."""

from __future__ import annotations

import FreeCAD as App
import FreeCADGui as Gui


def run():
    try:
        from PySide import QtCore, QtGui, QtWidgets  # type: ignore
    except ImportError:
        try:
            from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
        except ImportError:
            from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

    QShortcut = getattr(QtGui, "QShortcut", None) or getattr(
        QtWidgets, "QShortcut"
    )
    QTimer = QtCore.QTimer

    def _log(msg: str) -> None:
        # PrintMessage alone may not appear on the process stdout.
        App.Console.PrintError(f"TOOLSEEK_PROBE: {msg}\n")
        print(f"TOOLSEEK_PROBE: {msg}", flush=True)

    def check():
        mw = None
        try:
            cmds = list(Gui.listCommands())
            _log(f"ToolSeek_Open registered={('ToolSeek_Open' in cmds)}")
            _log(
                f"ToolSeek_Preferences registered="
                f"{('ToolSeek_Preferences' in cmds)}"
            )
            _log(
                f"NeoRibbon_Toggle registered={('NeoRibbon_Toggle' in cmds)}"
            )

            mw = Gui.getMainWindow()
            tools_titles = []
            if mw is not None:
                mb = mw.menuBar()
                tools_menu = None
                for act in mb.actions():
                    menu = act.menu()
                    title = (act.text() or "").replace("&", "").strip().lower()
                    if title == "tools":
                        tools_menu = menu
                        break
                if tools_menu is not None:
                    # Force the aboutToShow hook path FreeCAD users hit.
                    try:
                        tools_menu.aboutToShow.emit()
                    except Exception as exc:  # noqa: BLE001
                        _log(f"aboutToShow emit failed: {exc}")
                    for a in tools_menu.actions():
                        tools_titles.append(
                            (a.text() or "").replace("&", "").strip()
                        )
            _log(f"Tools menu items={tools_titles}")
            _log(
                "has ToolSeek="
                f"{any(t.startswith('ToolSeek') for t in tools_titles)}"
            )
            _log(
                "has NeoRibbon menu item="
                f"{any('NeoRibbon' in t or 'Toggle NeoRibbon' in t for t in tools_titles)}"
            )

            if mw is not None:
                scs = mw.findChildren(QShortcut)
                named = [
                    (sc.objectName(), sc.key().toString())
                    for sc in scs
                    if sc.objectName() or "Space" in sc.key().toString()
                ]
                _log(f"relevant QShortcuts={named}")
                ours = mw.findChild(QShortcut, "ToolSeek_OpenShortcut")
                if ours is None:
                    ours = mw.findChild(
                        QShortcut, "ToolSeek_CtrlSpaceShortcut"
                    )
                _log(f"ToolSeek shortcut present={ours is not None}")
                if ours is not None:
                    _log(f"ToolSeek shortcut key={ours.key().toString()}")

            # Shortcut recorder / preference page smoke (no modal UI).
            try:
                from toolseek.shortcut_edit import (
                    create_shortcut_recorder,
                    key_sequence_to_portable,
                    recorded_shortcut_text,
                    set_recorded_shortcut,
                )
                from toolseek.prefs_page import ToolSeekPreferencePage
                from toolseek import prefs as ts_prefs

                recorder = create_shortcut_recorder()
                set_recorded_shortcut(recorder, "Alt+P")
                got = recorded_shortcut_text(recorder)
                _log(f"shortcut recorder class={type(recorder).__name__}")
                _log(f"shortcut recorder Alt+P -> {got!r}")
                _log(
                    "shortcut recorder portable OK="
                    f"{key_sequence_to_portable(got).casefold() == 'alt+p'}"
                )
                set_recorded_shortcut(recorder, ts_prefs.DEFAULT_OPEN_SHORTCUT)
                _log(
                    "shortcut recorder default="
                    f"{recorded_shortcut_text(recorder)!r}"
                )

                page = ToolSeekPreferencePage()
                page.loadSettings()
                has_edit = hasattr(page, "open_shortcut")
                _log(f"prefs page has recorder={has_edit}")
                if has_edit:
                    set_recorded_shortcut(
                        page.open_shortcut, ts_prefs.DEFAULT_OPEN_SHORTCUT
                    )
                    _log(
                        "prefs page recorder="
                        f"{recorded_shortcut_text(page.open_shortcut)!r}"
                    )
            except Exception as exc:  # noqa: BLE001
                _log(f"shortcut recorder ERROR {type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            _log(f"ERROR {type(exc).__name__}: {exc}")
        finally:
            target = mw if mw is not None else Gui.getMainWindow()
            QTimer.singleShot(200, target.close)

    QTimer.singleShot(2500, check)


run()
