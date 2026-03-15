#!/usr/bin/env python3
"""CLI entry point for Tax-Automate-Germany."""

import argparse
import json
import sys
from pathlib import Path

from version import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="tax-automate-germany",
        description="Arbeitstage-Kalender: PDF-Generator fuer deutsche Steuerdokumentation",
    )
    parser.add_argument(
        "-m", "--metadata", default="metadata.json",
        help="Pfad zur metadata.json (Standard: metadata.json)",
    )
    parser.add_argument(
        "-y", "--year", type=int, nargs="*", default=None,
        help="Jahr(e) zum Generieren, z.B. -y 2022 2024 (Standard: alle)",
    )
    parser.add_argument(
        "-o", "--output-dir", default=None,
        help="Ausgabeverzeichnis fuer PDFs (Standard: selbes Verzeichnis wie metadata.json)",
    )
    parser.add_argument(
        "-a", "--anlage-n", action="store_true",
        help="Anlage N / Werbungskosten-Seite anhaengen",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Metadata pruefen und ohne PDF-Erzeugung beenden",
    )
    parser.add_argument(
        "--summary-json", default=None,
        help="Pfad fuer eine JSON-Zusammenfassung der berechneten Jahre",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Ausfuehrliche Ausgabe",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()
    meta_path = Path(args.metadata).resolve()

    if not meta_path.is_file():
        print(f"Fehler: {meta_path} nicht gefunden.")
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else meta_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    from generate_calendar import default_output_filename, generate_year
    from models import ValidationIssue, load_metadata, validate_metadata
    from tax_summary import is_supported_tax_year, supported_tax_years_label

    personal, year_configs = load_metadata(str(meta_path))

    if args.year:
        year_configs = [yc for yc in year_configs if yc.year in args.year]
        if not year_configs:
            print(f"Fehler: Keine Konfiguration fuer Jahr(e) {args.year} gefunden.")
            sys.exit(1)

    issues = validate_metadata(year_configs)
    for yc in year_configs:
        if not is_supported_tax_year(yc.year):
            issues.append(ValidationIssue(
                "ERROR",
                f"Steuerregeln fuer {yc.year} fehlen. Unterstuetzte Jahre: {supported_tax_years_label()}.",
                yc.year,
            ))

    errors = [issue for issue in issues if issue.level == "ERROR"]
    warnings = [issue for issue in issues if issue.level != "ERROR"]

    if warnings or errors:
        print("Metadata-Pruefung:")
        for issue in issues:
            print(f"  - {issue.render()}")
        print()

    if errors:
        print("Abbruch wegen fehlerhafter Konfiguration.")
        sys.exit(1)

    if args.validate:
        print("Metadata erfolgreich geprueft.")
        sys.exit(0)

    if args.verbose:
        print(f"Metadata: {meta_path}")
        print(f"Ausgabe: {output_dir}")
        print(f"Jahre: {[yc.year for yc in year_configs]}")
        print(f"Anlage N: {'ja' if args.anlage_n else 'nein'}")
        print()

    summaries = []
    for yc in year_configs:
        out_path = output_dir / default_output_filename(yc)
        summaries.append(generate_year(
            yc, personal, str(meta_path.parent), str(out_path),
            include_anlage_n=args.anlage_n, verbose=args.verbose,
        ))

    if args.summary_json:
        summary_path = Path(args.summary_json).resolve()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_payload = {
            "version": __version__,
            "metadata": str(meta_path),
            "years": summaries,
        }
        summary_path.write_text(
            json.dumps(summary_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON-Zusammenfassung geschrieben: {summary_path}")

    print(f"\nFertig. {len(year_configs)} PDF(s) erstellt in {output_dir}")


if __name__ == "__main__":
    main()
