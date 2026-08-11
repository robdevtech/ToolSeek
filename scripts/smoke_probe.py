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
                ours = mw.findChild(QShortcut, "ToolSeek_CtrlSpaceShortcut")
                _log(f"ToolSeek shortcut present={ours is not None}")
        except Exception as exc:  # noqa: BLE001
            _log(f"ERROR {type(exc).__name__}: {exc}")
        finally:
            target = mw if mw is not None else Gui.getMainWindow()
            QTimer.singleShot(200, target.close)

    QTimer.singleShot(2500, check)


run()
