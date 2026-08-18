# Changelog

All notable changes to ToolSeek are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-17

Tested stable release after the 0.2.x Addon Academy layout, quieter startup, Tools menu race hardening, and packaging extras.

### Added

- Live shortcut conflict check: a chord already used by FreeCAD is rejected as soon as it is recorded (warning dialog; previous shortcut kept). Reset is checked the same way.

## [0.2.4] - 2026-08-11

### Added

- Packaging extras for Addon Academy: `pyproject.toml`, Keep a Changelog `CHANGELOG.md`, dual licenses (`LICENSE-Code` / `LICENSE-Assets`), and `Resources/` (icons and media).

### Changed

- README paths and license notes updated for Academy packaging layout.

## [0.2.3] - 2026-08-11

### Changed

- Migrated to Addon Academy modern namespaced layout (`freecad/ToolSeek/`) with `package.xml` `<other>` content type (InitGui-only Mod, not a workbench).

## [0.2.2] - 2026-08-11

### Fixed

- Hardened Tools menu `aboutToShow` handling against deleted `QMenu` (NeoRibbon / custom UI).

### Changed

- Quiet clean startup in Report view; reserve Error/Warning for real failures and conflicts.

## [0.2.1] - 2026-08-11

### Fixed

- Tools menu race with NeoRibbon when `appendMenu` is ignored.
- Reduced Report-view noise on successful startup.

## [0.2.0] - 2026-08-10

### Added

- Command palette (type-to-find FreeCAD commands); default open shortcut **Ctrl+Space**.
- Preferences page (**Edit → Preferences → ToolSeek**): result style (icons/words), fuzzy matching, workbench switch on run, open-palette shortcut recorder with conflict checks.
- Ranking: menu labels over ids, word/prefix boosts, active-workbench preference, optional lightweight fuzzy match.
- Cross-workbench results with muted styling and best-effort workbench activation.
- Qt Tools menu injection and main-window `QShortcut` so NeoRibbon / custom UIs still get a reliable open path.
- README screenshots under `Images/`.

[0.3.0]: https://github.com/robdevtech/ToolSeek/releases/tag/v0.3.0
[0.2.4]: https://github.com/robdevtech/ToolSeek/releases/tag/v0.2.4
[0.2.3]: https://github.com/robdevtech/ToolSeek/releases/tag/v0.2.3
[0.2.2]: https://github.com/robdevtech/ToolSeek/releases/tag/v0.2.2
[0.2.1]: https://github.com/robdevtech/ToolSeek/releases/tag/v0.2.1
[0.2.0]: https://github.com/robdevtech/ToolSeek/releases/tag/v0.2.0
