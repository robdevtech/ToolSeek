# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD Gui commands registered by ToolSeek."""

from __future__ import annotations

import FreeCADGui as Gui

from .palette import show_palette

COMMAND_OPEN = "ToolSeek_Open"
COMMAND_PREFERENCES = "ToolSeek_Preferences"

# Back-compat alias used by bootstrap / tests.
COMMAND_NAME = COMMAND_OPEN


class OpenCommandSearch:
    """Open the ToolSeek command palette."""

    def GetResources(self):
        # Accel is intentionally omitted: FreeCAD often never wires Accel for
        # InitGui-only mods, and a QAction Accel would double-fire with our
        # QShortcut (open then immediately close). Default Ctrl+Space is
        # installed in bootstrap via QShortcut; Customize → Keyboard can still
        # assign an *additional* FreeCAD Accel if desired.
        return {
            "Pixmap": "edit-find",
            "MenuText": "ToolSeek…",
            "ToolTip": "Search and run FreeCAD commands by typing (Ctrl+Space)",
        }

    def Activated(self):
        show_palette()

    def IsActive(self):
        return True


class PreferencesCommand:
    """Open ToolSeek preferences (same ParamGet keys as Edit → Preferences)."""

    def GetResources(self):
        return {
            "Pixmap": "preferences-system",
            "MenuText": "ToolSeek preferences…",
            "ToolTip": "Open ToolSeek settings",
        }

    def Activated(self):
        from .prefs_dialog import open_preferences_dialog

        open_preferences_dialog()

    def IsActive(self):
        return True


def register():
    Gui.addCommand(COMMAND_OPEN, OpenCommandSearch())
    Gui.addCommand(COMMAND_PREFERENCES, PreferencesCommand())
