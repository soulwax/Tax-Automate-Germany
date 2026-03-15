# Tax-Automate-Germany

`Tax-Automate-Germany` generates PDF workday calendars for German tax documentation.
It is built for employees who want to document:

- office days
- home-office days
- public holidays by Bundesland
- vacation days
- commuting distance by period
- additional work-related expenses (`Werbungskosten`)

The application reads a local `metadata.json`, calculates yearly workday statistics, computes tax-relevant values such as `Entfernungspauschale` and `Homeoffice-Pauschale`, and renders a print-ready PDF.

Current version: `0.1.0`

Supported tax years in the current codebase: `2020` to `2026`

## Features

- Generate one PDF per tax year
- Optional Anlage-N / Werbungskosten summary page
- Regional holiday support with API lookup and local fallback
- Multi-period years:
  - move during the year
  - employer location changes
  - Bundesland changes
  - different commuting distances over time
- Two vacation modes:
  - explicit vacation dates via `Urlaubsdaten`
  - automatic heuristic allocation from the total number of vacation days
- Additional `Werbungskosten` support
- Metadata validation before generation
- Optional JSON export of computed yearly summaries

## Privacy And Safety

Your real `metadata.json` contains personal and tax-related information.

- Keep `metadata.json` private
- Do not commit it to Git
- Use `metadata-example.json` as your public template

The repository is already configured to ignore `metadata.json`.

## Requirements

- Python 3.11+ recommended
- Internet access is helpful for live holiday data
- If the holiday API is unavailable, the application falls back to local holiday calculation

Python dependencies:

- `reportlab`

Install dependencies with:

```bash
python -m pip install -r requirements.txt
```

## Quick Start

1. Copy the example file:

```bash
copy metadata-example.json metadata.json
```

On macOS or Linux:

```bash
cp metadata-example.json metadata.json
```

2. Edit `metadata.json` with your real data.

3. Validate the file:

```bash
python cli.py --validate -m metadata.json
```

4. Generate PDFs:

```bash
python cli.py -m metadata.json -a -v
```

This will create one PDF per configured tax year in the same directory as `metadata.json` unless you choose another output directory.

## CLI Usage

Basic form:

```bash
python cli.py [options]
```

Available options:

- `-m, --metadata`
  Path to the metadata file. Default: `metadata.json`
- `-y, --year`
  Restrict generation to one or more years
- `-o, --output-dir`
  Directory for generated PDFs
- `-a, --anlage-n`
  Append the Werbungskosten / Anlage-N page
- `--validate`
  Validate metadata and exit without creating PDFs
- `--summary-json`
  Write a machine-readable JSON summary of the computed results
- `-v, --verbose`
  Print extra runtime details
- `--version`
  Show the application version

Examples:

Validate only:

```bash
python cli.py --validate -m metadata.json
```

Generate all years:

```bash
python cli.py -m metadata.json -a
```

Generate only selected years:

```bash
python cli.py -m metadata.json -y 2024 2025 -a
```

Write PDFs into a dedicated directory:

```bash
python cli.py -m metadata.json -o output -a
```

Create a JSON summary in addition to the PDF:

```bash
python cli.py -m metadata.json -a --summary-json summary.json
```

## Metadata File Format

The application reads a JSON file with:

- personal information
- optional top-level yearly `Werbungskosten`
- one or more year configurations under `Jahr`

Use [metadata-example.json](/d:/Workspace/Python/Arbeitstage/metadata-example.json) as the starting point.

### Minimal Single-Period Example

```json
{
  "Vorname": "Max",
  "Nachname": "Mustermann",
  "Geburtsdatum": "01.01.1990",
  "Steuer-Identifikationsnummer": "12345678901",
  "Finanzamt-damals": "Berlin-Mitte",
  "Steuerklasse": "1",
  "Jahr": {
    "2025": [
      {
        "Arbeitstage": "Montag bis Freitag",
        "Feiertage": "Berlin",
        "Home-Office-Tage": "Montag",
        "Urlaubstage": "28",
        "Urlaubsdaten": [
          "14.04.2025 - 17.04.2025",
          "30.05.2025"
        ],
        "Addresse_Zuhause": "Musterstrasse 1, 10115 Berlin",
        "Addresse_Arbeit": "Beispielweg 10, 10247 Berlin",
        "Kilometer_Entfernung": "5",
        "Kartendatei": "map.png",
        "Kommentar": "Mit dem Auto meist 15-20 Minuten."
      }
    ]
  }
}
```

### Multi-Period Example

Use multiple period objects in one year when something changes mid-year:

- home address
- work address
- Bundesland for holidays
- commuting distance
- workday pattern
- home-office pattern

Example:

```json
{
  "Jahr": {
    "2025": [
      {
        "Ab": "01.01.2025",
        "Bis": "30.06.2025",
        "Arbeitstage": "Montag bis Freitag",
        "Feiertage": "Berlin",
        "Home-Office-Tage": "Montag",
        "Urlaubstage": "30",
        "Urlaubsdaten": [
          "14.04.2025 - 17.04.2025",
          "30.05.2025"
        ],
        "Addresse_Zuhause": "Berlin, Beispielstrasse 1",
        "Addresse_Arbeit": "Berlin, Bueroallee 10",
        "Kilometer_Entfernung": "5",
        "Kartendatei": "maps/route_berlin.png"
      },
      {
        "Ab": "01.07.2025",
        "Arbeitstage": "Montag bis Freitag",
        "Feiertage": "Hessen",
        "Home-Office-Tage": "Montag und Freitag",
        "Urlaubstage": "30",
        "Urlaubsdaten": [
          "22.12.2025 - 24.12.2025"
        ],
        "Addresse_Zuhause": "Frankfurt, Beispielstrasse 22",
        "Addresse_Arbeit": "Frankfurt, Taetigkeitsweg 3",
        "Kilometer_Entfernung": "28",
        "Kartendatei": "maps/route_frankfurt.png"
      }
    ]
  }
}
```

Notes:

- The first period starts on `01.01.YYYY` if `Ab` is omitted
- The last period ends on `31.12.YYYY` if `Bis` is omitted
- Intermediate missing `Bis` values are inferred from the next period
- Periods must not overlap

## Supported Metadata Fields

### Personal Fields

These fields are optional but useful for the cover page:

- `AppName`
- `Vorname`
- `Nachname`
- `Geburtsdatum`
- `Steuer-Identifikationsnummer`
- `Finanzamt-damals`
- `Steuerklasse`
- `Addresse_Arbeitgeber_Heute`

### Per-Year Section

Each entry under `Jahr` is an array of one or more period objects.

Recognized per-period fields:

- `Ab`
- `Bis`
- `Arbeitstage`
- `Feiertage`
- `Home-Office-Tage`
- `Urlaubstage`
- `Urlaubsdaten`
- `Addresse_Zuhause`
- `Addresse_Arbeit`
- `Kilometer_Entfernung`
- `Kartendatei`
- `Kommentar`
- `Werbungskosten`
- `Zusätzliche_Werbungskosten`
- `Weitere_Werbungskosten`

Recognized yearly expense containers at the top level:

- `Werbungskosten`
- `Zusätzliche_Werbungskosten`
- `Weitere_Werbungskosten`

Recommended format for yearly expenses:

```json
{
  "Werbungskosten": {
    "2025": [
      {
        "Kategorie": "Arbeitsmittel",
        "Beschreibung": "Monitor und Tastatur",
        "Betrag": "245,90"
      },
      {
        "Kategorie": "Kontofuehrung",
        "Hinweis": "Pauschal",
        "Betrag": "16,00"
      }
    ]
  }
}
```

Expense entries can be given as:

- a list of objects with `Kategorie`, `Betrag`, and optional `Beschreibung` or `Hinweis`
- a simple object mapping categories to amounts

## Field Semantics

### `Arbeitstage`

Examples:

- `Montag bis Freitag`
- `Montag bis Donnerstag`
- `Montag Mittwoch Freitag`

### `Home-Office-Tage`

Examples:

- `Montag`
- `Montag und Freitag`
- `Dienstag, Donnerstag`

Only configured workdays can become home-office days.

### `Feiertage`

This is the Bundesland used for public holiday calculation.

Examples:

- `Berlin`
- `Hessen`
- `Bayern`

For multi-period years, each period can use a different Bundesland.

### `Urlaubstage`

This is the yearly total number of vacation days used for validation and reporting.

### `Urlaubsdaten`

This is the preferred, audit-friendly way to document vacation.

Supported formats:

- single day: `30.05.2025`
- date range: `14.04.2025 - 17.04.2025`
- list of strings

If `Urlaubsdaten` is present, the generator uses those explicit dates.
If it is absent, the application falls back to an automatic heuristic allocation of vacation days around bridge days and year-end periods.

### `Kilometer_Entfernung`

This is the one-way distance between home and the first place of work.
The calculation uses the tax rules for the configured year.

### `Kartendatei`

Optional relative path to a route image shown in the PDF.
The path is resolved relative to the folder containing `metadata.json`.

## Output Files

The application can produce:

- yearly PDF files such as `Arbeitstage_2025_Berlin.pdf`
- optionally a JSON summary file when `--summary-json` is used

For multi-state years, the default filename becomes:

- `Arbeitstage_<year>_Mehrere_Bundeslaender.pdf`

## What Is In The PDF

The PDF can include:

1. Cover page
   - personal data
   - work configuration
   - tax-relevant key figures
   - holiday list
   - addresses
   - route map if provided
2. Monthly calendar pages
   - office days
   - home-office days
   - holidays
   - weekends
   - vacation days
3. Year summary page
   - monthly totals
   - yearly totals
   - chart
4. Optional Anlage-N page
   - commuting allowance
   - home-office allowance
   - additional expenses
   - comparison with the Arbeitnehmer-Pauschbetrag

## JSON Summary Export

When `--summary-json` is used, the application writes a JSON document with:

- application version
- metadata path
- one computed result per year

Included data includes:

- states per period
- vacation mode and allocation stats
- workday totals
- Werbungskosten totals
- period breakdown
- additional expense breakdown
- output PDF path

This export is useful for:

- record keeping
- quick review before filing
- post-processing in other tools

## Validation Behavior

Run validation explicitly with:

```bash
python cli.py --validate -m metadata.json
```

Validation checks include:

- at least one configured year
- non-overlapping periods
- periods inside the declared tax year
- missing or empty workday configuration
- negative commuting distance
- invalid or out-of-period vacation dates
- mismatch between `Urlaubstage` and explicit `Urlaubsdaten`
- negative additional expenses

Warnings do not stop generation.
Errors stop generation.

Common warning example:

- You declared `Urlaubstage: 30` but documented only 12 explicit vacation days

## Tax Logic In This Version

The current codebase contains year-specific rules for:

- `Entfernungspauschale`
- `Homeoffice-Pauschale`
- `Arbeitnehmer-Pauschbetrag`

Important behavior:

- Unsupported tax years are rejected instead of silently using the latest known rule
- The current implementation supports tax years `2020` through `2026`

## Development

Run tests:

```bash
python -m unittest discover -s tests -v
```

Run a syntax check:

```bash
python -m py_compile cli.py generate_calendar.py models.py tax_summary.py version.py
```

## Typical Workflow

1. Copy `metadata-example.json` to `metadata.json`
2. Fill in personal data
3. Add one or more yearly configurations under `Jahr`
4. Add explicit `Urlaubsdaten` if available
5. Add optional `Werbungskosten`
6. Run validation
7. Generate the PDF
8. Keep the PDF and optional JSON summary with your tax records

## Troubleshooting

### `Fehler: ... metadata.json nicht gefunden`

The path passed via `-m` does not exist.
Check the filename and working directory.

### `Abbruch wegen fehlerhafter Konfiguration`

Run validation and fix the reported `ERROR` entries:

```bash
python cli.py --validate -m metadata.json
```

### Route image does not appear

Check that:

- `Kartendatei` exists
- the path is relative to the metadata file directory
- the image file can be read by Python

### Holiday data looks wrong

Check the `Feiertage` value in each period.
If you changed Bundesland during the year, split the year into multiple periods.

### Vacation totals look incomplete

If you use explicit `Urlaubsdaten`, make sure you entered all relevant vacation dates.
Otherwise the report will correctly show that only part of the yearly total is documented.

## Limitations

- This tool helps document tax-relevant work patterns, but it is not tax advice
- The output should be checked against your own records and the current tax forms
- Special tax situations outside the implemented rules may require manual review

## Related Files

- [cli.py](/d:/Workspace/Python/Arbeitstage/cli.py)
- [generate_calendar.py](/d:/Workspace/Python/Arbeitstage/generate_calendar.py)
- [models.py](/d:/Workspace/Python/Arbeitstage/models.py)
- [tax_summary.py](/d:/Workspace/Python/Arbeitstage/tax_summary.py)
- [metadata-example.json](/d:/Workspace/Python/Arbeitstage/metadata-example.json)
- [CHANGELOG.md](/d:/Workspace/Python/Arbeitstage/CHANGELOG.md)
