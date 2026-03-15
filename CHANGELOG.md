# Changelog

## 0.1.0 - 2026-03-15

### Added
- Explicit `Urlaubsdaten` support so vacation can be documented with exact dates instead of only being estimated from a total count.
- Configurable additional `Werbungskosten` items that are included in the Anlage-N summary and JSON exports.
- CLI metadata validation via `--validate`, JSON summary export via `--summary-json`, and `--version`.

### Changed
- Holiday handling is now period-aware, so multi-period years can switch Bundesland mid-year without losing the correct regional holidays.
- Cover and Anlage-N summaries now distinguish documented vacation from auto-planned vacation and show extra deductions separately.

### Fixed
- Updated the 2026 `Entfernungspauschale` to 0,38 EUR from the first kilometer in line with the current EStG.
- Unsupported tax years no longer silently fall back to the latest known rule set.
