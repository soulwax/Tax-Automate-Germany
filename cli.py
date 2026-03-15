#!/usr/bin/env python3
"""CLI entry point for Tax-Automate-Germany."""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="tax-automate-germany",
        description="Arbeitstage-Kalender: PDF-Generator für deutsche Steuerdokumentation",
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
        help="Ausgabeverzeichnis für PDFs (Standard: selbes Verzeichnis wie metadata.json)",
    )
    parser.add_argument(
        "-a", "--anlage-n", action="store_true",
        help="Anlage N / Werbungskosten-Seite anhängen",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Ausführliche Ausgabe",
    )

    args = parser.parse_args()
    meta_path = Path(args.metadata).resolve()

    if not meta_path.is_file():
        print(f"Fehler: {meta_path} nicht gefunden.")
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else meta_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    from models import load_metadata
    from generate_calendar import generate_year

    personal, year_configs = load_metadata(str(meta_path))

    if args.year:
        year_configs = [yc for yc in year_configs if yc.year in args.year]
        if not year_configs:
            print(f"Fehler: Keine Konfiguration für Jahr(e) {args.year} gefunden.")
            sys.exit(1)

    if args.verbose:
        print(f"Metadata: {meta_path}")
        print(f"Ausgabe: {output_dir}")
        print(f"Jahre: {[yc.year for yc in year_configs]}")
        print(f"Anlage N: {'ja' if args.anlage_n else 'nein'}")
        print()

    for yc in year_configs:
        out_path = output_dir / f"Arbeitstage_{yc.year}_{yc.bundesland}.pdf"
        generate_year(
            yc, personal, str(meta_path.parent), str(out_path),
            include_anlage_n=args.anlage_n, verbose=args.verbose,
        )

    print(f"\nFertig. {len(year_configs)} PDF(s) erstellt in {output_dir}")


if __name__ == "__main__":
    main()
