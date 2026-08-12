# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI bootstrap for ToolSeek (FreeCAD imports freecad.ToolSeek.init_gui)."""

import FreeCAD as App

try:
    from freecad.ToolSeek.bootstrap import install

    install()
except Exception as exc:
    App.Console.PrintError(f"ToolSeek failed to start: {exc}\n")
    raise
