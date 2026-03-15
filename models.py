"""Data models, parsing, and validation for Tax-Automate-Germany."""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DAY_MAP = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}

LAND_CODES = {
    "baden-württemberg": "BW", "bayern": "BY", "berlin": "BE",
    "brandenburg": "BB", "bremen": "HB", "hamburg": "HH",
    "hessen": "HE", "mecklenburg-vorpommern": "MV",
    "niedersachsen": "NI", "nordrhein-westfalen": "NW",
    "rheinland-pfalz": "RP", "saarland": "SL", "sachsen": "SN",
    "sachsen-anhalt": "ST", "schleswig-holstein": "SH",
    "thüringen": "TH",
    "bw": "BW", "by": "BY", "be": "BE", "bb": "BB", "hb": "HB",
    "hh": "HH", "he": "HE", "mv": "MV", "ni": "NI", "nw": "NW",
    "rp": "RP", "sl": "SL", "sn": "SN", "st": "ST", "sh": "SH", "th": "TH",
}

VACATION_KEYS = (
    "Urlaubsdaten",
    "Urlaubstage_Liste",
    "Urlaubstage-Liste",
)

EXPENSE_KEYS = (
    "Werbungskosten",
    "Zusätzliche_Werbungskosten",
    "Weitere_Werbungskosten",
)


@dataclass
class PersonalData:
    app_name: str = ""
    vorname: str = ""
    nachname: str = ""
    geburtsdatum: str = ""
    steuer_id: str = ""
    finanzamt: str = ""
    steuerklasse: str = ""
    adresse_arbeitgeber_heute: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.vorname} {self.nachname}".strip()


@dataclass
class AdditionalExpense:
    category: str
    amount: float
    description: str = ""
    note: str = ""


@dataclass
class PeriodConfig:
    """One contiguous work period within a year (may span full year or a sub-range)."""

    start_date: datetime.date
    end_date: datetime.date
    bundesland: str = "Hessen"
    land_code: str = "HE"
    workdays: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4})
    ho_days: set[int] = field(default_factory=set)
    ho_label: str = ""
    work_label: str = "Montag bis Freitag"
    addr_home: str = ""
    addr_work: str = ""
    km: float = 0.0
    map_file: str = ""
    kommentar: str = ""
    vacation_dates: set[datetime.date] = field(default_factory=set)

    @property
    def label(self) -> str:
        if (self.start_date.month == 1 and self.start_date.day == 1
                and self.end_date.month == 12 and self.end_date.day == 31):
            return "Ganzjährig"
        return f"{self.start_date.strftime('%d.%m.')} - {self.end_date.strftime('%d.%m.')}"


@dataclass
class YearConfig:
    year: int
    periods: list[PeriodConfig] = field(default_factory=list)
    total_urlaub: int = 0
    explicit_urlaub_dates: set[datetime.date] = field(default_factory=set)
    additional_expenses: list[AdditionalExpense] = field(default_factory=list)

    @property
    def bundesland(self) -> str:
        return self.periods[0].bundesland if self.periods else "Hessen"

    @property
    def land_code(self) -> str:
        return self.periods[0].land_code if self.periods else "HE"

    @property
    def uses_multiple_states(self) -> bool:
        return len({p.land_code for p in self.periods}) > 1

    @property
    def has_explicit_urlaub(self) -> bool:
        return bool(self.explicit_urlaub_dates)

    def period_for_date(self, d: datetime.date) -> PeriodConfig:
        for p in self.periods:
            if p.start_date <= d <= p.end_date:
                return p
        return self.periods[-1]  # fallback

    def period_index(self, d: datetime.date) -> int:
        for i, p in enumerate(self.periods):
            if p.start_date <= d <= p.end_date:
                return i
        return len(self.periods) - 1


@dataclass
class ValidationIssue:
    level: str
    message: str
    year: int | None = None

    def render(self) -> str:
        prefix = f"{self.level}: "
        if self.year is None:
            return prefix + self.message
        return prefix + f"Jahr {self.year}: {self.message}"


def parse_date(s: str) -> datetime.date:
    """Parse DD.MM.YYYY format."""
    parts = s.strip().split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"Ungueltiges Datum: {s!r}")
    return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))


def parse_workdays(t: str) -> set[int]:
    t = t.strip().lower()
    if " bis " in t:
        a, b = t.split(" bis ", 1)
        return set(range(DAY_MAP[a.strip()], DAY_MAP[b.strip()] + 1))
    return {DAY_MAP[w.strip()] for w in t.replace(",", " ").replace("und", " ").split()
            if w.strip() in DAY_MAP}


def parse_ho(t: str) -> set[int]:
    return {DAY_MAP[w.strip()] for w in t.strip().lower().replace(",", " ").replace("und", " ").split()
            if w.strip() in DAY_MAP}


def parse_km(t: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(t))
    return float(m.group(1).replace(",", ".")) if m else 0.0


def parse_amount(value: Any) -> float:
    m = re.search(r"(-?\d+(?:[.,]\d+)?)", str(value))
    if not m:
        raise ValueError(f"Kein Betrag gefunden: {value!r}")
    return float(m.group(1).replace(",", "."))


def _resolve_km(cfg: dict) -> float:
    """Try multiple possible km field names for backwards compat."""
    for key in ("Kilometer_Entfernung", "Kilometer_entfernung",
                "Kilometer_Entfernung_2022_2023", "Kilometer_Entfernung_2023_2024",
                "Kilometer_entfernung_2023_2024"):
        if key in cfg:
            return parse_km(cfg[key])
    return 0.0


def _iter_entries(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        return [part.strip() for part in text.split(",") if part.strip()]
    return [value]


def _expand_date_entry(entry: str) -> set[datetime.date]:
    text = str(entry).strip()
    if not text:
        return set()

    for sep in (" bis ", " - ", " – ", " — "):
        if sep in text:
            start_raw, end_raw = text.split(sep, 1)
            start = parse_date(start_raw)
            end = parse_date(end_raw)
            if end < start:
                raise ValueError(f"Urlaubszeitraum endet vor dem Beginn: {text!r}")
            days = set()
            current = start
            while current <= end:
                days.add(current)
                current += datetime.timedelta(days=1)
            return days

    return {parse_date(text)}


def parse_vacation_dates(value: Any) -> set[datetime.date]:
    dates: set[datetime.date] = set()
    for entry in _iter_entries(value):
        if isinstance(entry, str):
            dates.update(_expand_date_entry(entry))
        else:
            raise ValueError(f"Urlaubsdaten muessen als Text angegeben werden: {entry!r}")
    return dates


def _parse_expense_entry(entry: Any) -> list[AdditionalExpense]:
    if isinstance(entry, dict):
        if "Kategorie" in entry or "Betrag" in entry or "Beschreibung" in entry:
            amount = parse_amount(entry.get("Betrag", 0))
            return [AdditionalExpense(
                category=str(entry.get("Kategorie", "Sonstige Werbungskosten")).strip()
                or "Sonstige Werbungskosten",
                amount=amount,
                description=str(entry.get("Beschreibung", "")).strip(),
                note=str(entry.get("Hinweis", "")).strip(),
            )]

        items = []
        for category, raw_amount in entry.items():
            items.append(AdditionalExpense(
                category=str(category).strip() or "Sonstige Werbungskosten",
                amount=parse_amount(raw_amount),
            ))
        return items

    raise ValueError(f"Ungueltiger Werbungskosten-Eintrag: {entry!r}")


def parse_additional_expenses(value: Any) -> list[AdditionalExpense]:
    expenses: list[AdditionalExpense] = []
    for entry in _iter_entries(value):
        expenses.extend(_parse_expense_entry(entry))
    return expenses


def _collect_period_vacations(cfg: dict) -> set[datetime.date]:
    for key in VACATION_KEYS:
        if key in cfg:
            return parse_vacation_dates(cfg[key])
    return set()


def _collect_year_expenses(data: dict, year_str: str, configs: list[dict]) -> list[AdditionalExpense]:
    expenses: list[AdditionalExpense] = []

    for key in EXPENSE_KEYS:
        section = data.get(key)
        if isinstance(section, dict) and year_str in section:
            expenses.extend(parse_additional_expenses(section[year_str]))

    for cfg in configs:
        for key in EXPENSE_KEYS:
            if key in cfg:
                expenses.extend(parse_additional_expenses(cfg[key]))

    return expenses


def load_metadata(path: str | Path) -> tuple[PersonalData, list[YearConfig]]:
    """Load metadata.json and return structured data."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    personal = PersonalData(
        app_name=data.get("AppName", ""),
        vorname=data.get("Vorname", ""),
        nachname=data.get("Nachname", ""),
        geburtsdatum=data.get("Geburtsdatum", ""),
        steuer_id=data.get("Steuer-Identifikationsnummer", ""),
        finanzamt=data.get("Finanzamt-damals", ""),
        steuerklasse=data.get("Steuerklasse", ""),
        adresse_arbeitgeber_heute=data.get("Addresse_Arbeitgeber_Heute", ""),
    )

    year_configs = []
    for year_str, configs in data.get("Jahr", {}).items():
        year = int(year_str)
        jan1 = datetime.date(year, 1, 1)
        dec31 = datetime.date(year, 12, 31)

        total_urlaub = int(configs[0].get("Urlaubstage", "0"))

        periods = []
        explicit_urlaub_dates: set[datetime.date] = set()
        for i, cfg in enumerate(configs):
            if "Ab" in cfg:
                start = parse_date(cfg["Ab"])
            elif i == 0:
                start = jan1
            else:
                start = periods[-1].end_date + datetime.timedelta(1)

            if "Bis" in cfg:
                end = parse_date(cfg["Bis"])
            elif i == len(configs) - 1:
                end = dec31
            else:
                end = dec31

            bundesland = cfg.get("Feiertage", "Hessen")
            lc = LAND_CODES.get(bundesland.lower(), "HE")
            vacation_dates = _collect_period_vacations(cfg)
            explicit_urlaub_dates.update(vacation_dates)

            periods.append(PeriodConfig(
                start_date=start,
                end_date=end,
                bundesland=bundesland,
                land_code=lc,
                workdays=parse_workdays(cfg.get("Arbeitstage", "Montag bis Freitag")),
                ho_days=parse_ho(cfg.get("Home-Office-Tage", "")),
                ho_label=cfg.get("Home-Office-Tage", "").strip(),
                work_label=cfg.get("Arbeitstage", "Montag bis Freitag").strip(),
                addr_home=cfg.get("Addresse_Zuhause", ""),
                addr_work=cfg.get("Addresse_Arbeit", ""),
                km=_resolve_km(cfg),
                map_file=cfg.get("Kartendatei", ""),
                kommentar=cfg.get("Kommentar", ""),
                vacation_dates=vacation_dates,
            ))

        for i in range(len(periods) - 1):
            if "Bis" not in configs[i]:
                periods[i].end_date = periods[i + 1].start_date - datetime.timedelta(1)

        year_configs.append(YearConfig(
            year=year,
            periods=periods,
            total_urlaub=total_urlaub,
            explicit_urlaub_dates=explicit_urlaub_dates,
            additional_expenses=_collect_year_expenses(data, year_str, configs),
        ))

    return personal, year_configs


def validate_metadata(year_configs: list[YearConfig]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not year_configs:
        issues.append(ValidationIssue("ERROR", "Keine Jahreskonfiguration gefunden."))
        return issues

    for yc in year_configs:
        if not yc.periods:
            issues.append(ValidationIssue("ERROR", "Keine Zeitraeume konfiguriert.", yc.year))
            continue

        previous_end: datetime.date | None = None
        configured_explicit = 0
        usable_explicit = 0

        for period in yc.periods:
            if period.start_date.year != yc.year or period.end_date.year != yc.year:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Zeitraum {period.label} liegt nicht vollstaendig im Steuerjahr.",
                    yc.year,
                ))
            if period.end_date < period.start_date:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Zeitraum {period.label} endet vor dem Beginn.",
                    yc.year,
                ))
            if previous_end and period.start_date <= previous_end:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Zeitraum {period.label} ueberschneidet sich mit dem vorherigen Zeitraum.",
                    yc.year,
                ))
            previous_end = period.end_date

            if not period.workdays:
                issues.append(ValidationIssue(
                    "WARN",
                    f"Zeitraum {period.label} hat keine Arbeitstage konfiguriert.",
                    yc.year,
                ))

            if period.km < 0:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Zeitraum {period.label} hat eine negative Kilometerangabe.",
                    yc.year,
                ))

            configured_explicit += len(period.vacation_dates)
            for vacation_date in sorted(period.vacation_dates):
                if vacation_date.year != yc.year:
                    issues.append(ValidationIssue(
                        "ERROR",
                        f"Urlaubsdatum {vacation_date:%d.%m.%Y} liegt ausserhalb des Steuerjahrs.",
                        yc.year,
                    ))
                    continue

                if not (period.start_date <= vacation_date <= period.end_date):
                    issues.append(ValidationIssue(
                        "ERROR",
                        f"Urlaubsdatum {vacation_date:%d.%m.%Y} liegt ausserhalb des Zeitraums {period.label}.",
                        yc.year,
                    ))
                    continue

                if vacation_date.weekday() not in period.workdays:
                    issues.append(ValidationIssue(
                        "WARN",
                        f"Urlaubsdatum {vacation_date:%d.%m.%Y} faellt auf einen arbeitsfreien Tag.",
                        yc.year,
                    ))
                else:
                    usable_explicit += 1

        if yc.has_explicit_urlaub:
            if usable_explicit < yc.total_urlaub:
                issues.append(ValidationIssue(
                    "WARN",
                    f"Es sind nur {usable_explicit} nutzbare Urlaubstage dokumentiert, aber {yc.total_urlaub} angegeben.",
                    yc.year,
                ))
            if usable_explicit > yc.total_urlaub:
                issues.append(ValidationIssue(
                    "WARN",
                    f"Es sind {usable_explicit} nutzbare Urlaubstage dokumentiert, aber nur {yc.total_urlaub} angegeben.",
                    yc.year,
                ))
            if configured_explicit != len(yc.explicit_urlaub_dates):
                issues.append(ValidationIssue(
                    "WARN",
                    "Mindestens ein Urlaubsdatum ist in mehreren Zeitraeumen doppelt hinterlegt.",
                    yc.year,
                ))
        elif yc.total_urlaub > 0:
            issues.append(ValidationIssue(
                "WARN",
                "Es sind nur Urlaubstage als Anzahl hinterlegt; ohne konkrete Urlaubsdaten bleibt die Doku heuristisch.",
                yc.year,
            ))

        for expense in yc.additional_expenses:
            if expense.amount < 0:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Werbungskosten-Posten {expense.category!r} hat einen negativen Betrag.",
                    yc.year,
                ))
            if not expense.category:
                issues.append(ValidationIssue(
                    "WARN",
                    "Ein Werbungskosten-Posten hat keine Kategorie.",
                    yc.year,
                ))

    return issues
