"""Data models and metadata parser for Tax-Automate-Germany."""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

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

    @property
    def bundesland(self) -> str:
        return self.periods[0].bundesland if self.periods else "Hessen"

    @property
    def land_code(self) -> str:
        return self.periods[0].land_code if self.periods else "HE"

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


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_date(s: str) -> datetime.date:
    """Parse DD.MM.YYYY format."""
    parts = s.strip().split(".")
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


def _resolve_km(cfg: dict) -> float:
    """Try multiple possible km field names for backwards compat."""
    for key in ("Kilometer_Entfernung", "Kilometer_entfernung",
                "Kilometer_Entfernung_2022_2023", "Kilometer_Entfernung_2023_2024",
                "Kilometer_entfernung_2023_2024"):
        if key in cfg:
            return parse_km(cfg[key])
    return 0.0


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

        # Get total vacation from first config
        total_urlaub = int(configs[0].get("Urlaubstage", "0"))

        periods = []
        for i, cfg in enumerate(configs):
            # Determine period boundaries
            if "Ab" in cfg:
                start = parse_date(cfg["Ab"])
            elif i == 0:
                start = jan1
            else:
                # starts day after previous period ends
                start = periods[-1].end_date + datetime.timedelta(1)

            if "Bis" in cfg:
                end = parse_date(cfg["Bis"])
            elif i == len(configs) - 1:
                end = dec31
            else:
                # Will be determined when next period is parsed
                # For now use dec31, will be adjusted
                end = dec31

            bundesland = cfg.get("Feiertage", "Hessen")
            lc = LAND_CODES.get(bundesland.lower(), "HE")

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
            ))

        # Fix period boundaries: ensure contiguous and no overlap
        for i in range(len(periods) - 1):
            if "Bis" not in configs[i]:
                periods[i].end_date = periods[i + 1].start_date - datetime.timedelta(1)

        year_configs.append(YearConfig(
            year=year,
            periods=periods,
            total_urlaub=total_urlaub,
        ))

    return personal, year_configs
