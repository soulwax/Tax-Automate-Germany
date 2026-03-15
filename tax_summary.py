"""Werbungskosten / Anlage N computation and PDF page rendering."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer

from models import YearConfig, PeriodConfig

# ---------------------------------------------------------------------------
# Tax constants by year
# ---------------------------------------------------------------------------
TAX_RULES: dict[int, dict] = {
    # year: {ho_rate, ho_cap_days, ep_rate_20, ep_rate_21plus, pauschbetrag}
    2020: {"ho_rate": 5.0, "ho_cap": 120, "ep20": 0.30, "ep21": 0.30, "pausch": 1000},
    2021: {"ho_rate": 5.0, "ho_cap": 120, "ep20": 0.30, "ep21": 0.35, "pausch": 1000},
    2022: {"ho_rate": 5.0, "ho_cap": 120, "ep20": 0.30, "ep21": 0.38, "pausch": 1200},
    2023: {"ho_rate": 6.0, "ho_cap": 210, "ep20": 0.30, "ep21": 0.38, "pausch": 1230},
    2024: {"ho_rate": 6.0, "ho_cap": 210, "ep20": 0.30, "ep21": 0.38, "pausch": 1230},
    2025: {"ho_rate": 6.0, "ho_cap": 210, "ep20": 0.30, "ep21": 0.38, "pausch": 1230},
}


def _rules(year: int) -> dict:
    """Get tax rules for a year, defaulting to latest known."""
    if year in TAX_RULES:
        return TAX_RULES[year]
    return TAX_RULES[max(TAX_RULES.keys())]


# ---------------------------------------------------------------------------
# Entfernungspauschale
# ---------------------------------------------------------------------------
def entfernungspauschale(km: float, tage: int, year: int) -> float:
    """Compute EP for one-way km distance and number of Büro days."""
    r = _rules(year)
    if km <= 20:
        return km * r["ep20"] * tage
    basis = 20 * r["ep20"] * tage
    extra = (km - 20) * r["ep21"] * tage
    return basis + extra


# ---------------------------------------------------------------------------
# Homeoffice-Pauschale
# ---------------------------------------------------------------------------
def homeoffice_pauschale(ho_tage: int, year: int) -> float:
    r = _rules(year)
    capped = min(ho_tage, r["ho_cap"])
    return capped * r["ho_rate"]


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class PeriodResult:
    label: str
    km: float
    buero_tage: int
    ho_tage: int
    ep: float
    km_total: float


@dataclass
class WerbungskostenResult:
    year: int
    periods: list[PeriodResult] = field(default_factory=list)
    total_buero: int = 0
    total_ho: int = 0
    total_ep: float = 0.0
    total_km: float = 0.0
    ho_pauschale: float = 0.0
    ho_rate: float = 0.0
    ho_cap: int = 0
    ho_capped: int = 0
    werbungskosten_total: float = 0.0
    pauschbetrag: float = 0.0

    @property
    def above_pauschbetrag(self) -> bool:
        return self.werbungskosten_total > self.pauschbetrag

    @property
    def net_benefit(self) -> float:
        return max(0, self.werbungskosten_total - self.pauschbetrag)


def compute_werbungskosten(
    year: int,
    yc: YearConfig,
    dm: dict,
) -> WerbungskostenResult:
    """Compute full Werbungskosten from day-map and period configs."""
    r = _rules(year)
    result = WerbungskostenResult(year=year)
    result.ho_rate = r["ho_rate"]
    result.ho_cap = r["ho_cap"]
    result.pauschbetrag = r["pausch"]

    # Count Büro and HO days per period
    from generate_calendar import T  # local import to avoid circular
    for i, period in enumerate(yc.periods):
        buero = 0
        ho = 0
        d = period.start_date
        while d <= period.end_date:
            if d in dm and isinstance(dm[d], tuple):
                if dm[d][0] == T.B:
                    buero += 1
                elif dm[d][0] == T.H:
                    ho += 1
            d += datetime.timedelta(1)

        ep = entfernungspauschale(period.km, buero, year)
        km_total = period.km * buero

        result.periods.append(PeriodResult(
            label=period.label,
            km=period.km,
            buero_tage=buero,
            ho_tage=ho,
            ep=ep,
            km_total=km_total,
        ))
        result.total_buero += buero
        result.total_ho += ho
        result.total_ep += ep
        result.total_km += km_total

    result.ho_capped = min(result.total_ho, r["ho_cap"])
    result.ho_pauschale = homeoffice_pauschale(result.total_ho, year)
    result.werbungskosten_total = result.total_ep + result.ho_pauschale

    return result


# ---------------------------------------------------------------------------
# PDF page rendering
# ---------------------------------------------------------------------------
# Colors (reuse from generate_calendar)
C_HDR   = colors.HexColor("#1B2631")
C_HDR2  = colors.HexColor("#2C3E50")
C_WHITE = colors.HexColor("#FFFFFF")
C_DARK  = colors.HexColor("#1B2631")
C_MID   = colors.HexColor("#5D6D7E")
C_LIGHT = colors.HexColor("#D5D8DC")
C_FAINT = colors.HexColor("#F2F3F4")
C_GREEN = colors.HexColor("#27AE60")
C_ACCENT = colors.HexColor("#2980B9")
C_BLUE_L = colors.HexColor("#85C1E9")
C_ORANGE = colors.HexColor("#E67E22")
C_RED_SOFT = colors.HexColor("#E74C3C")


def _ps(name, sz=7.5, bold=False, color=C_DARK, align=TA_CENTER, lead=None):
    return ParagraphStyle(
        name, fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=sz, leading=lead or sz + 2, textColor=color, alignment=align)


def _fmt_eur(v: float) -> str:
    """Format as German EUR string."""
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} EUR"


def render_anlage_n_page(wk: WerbungskostenResult, pw: float) -> list:
    """Return reportlab flowables for the Anlage N summary page."""
    elements = []

    # Title
    title_data = [[
        Paragraph(f"<b>WERBUNGSKOSTEN / ANLAGE N  --  Steuerjahr {wk.year}</b>",
                  _ps("AN_T", 14, True, C_WHITE, TA_LEFT)),
    ]]
    title_tbl = Table(title_data, colWidths=[pw])
    title_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_HDR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(title_tbl)
    elements.append(Spacer(1, 5 * mm))

    # --- Section 1: Entfernungspauschale ---
    hs = _ps("AN_H", 7.5, True, C_WHITE)
    vs = _ps("AN_V", 7.5)
    vb = _ps("AN_VB", 8, True, C_DARK)

    ep_header = [Paragraph(h, hs) for h in [
        "Zeitraum", "Entfernung", "Bürotage", "km gesamt (einf.)",
        "Satz (0-20km)", "Satz (ab 21km)", "Pauschale"
    ]]
    ep_data = [ep_header]
    r = _rules(wk.year)

    for i, pr in enumerate(wk.periods):
        ep_data.append([
            Paragraph(pr.label, _ps(f"AN_PL{i}", 7.5, color=C_DARK, align=TA_LEFT)),
            Paragraph(f"{pr.km:.0f} km", _ps(f"AN_PK{i}", 7.5)),
            Paragraph(str(pr.buero_tage), _ps(f"AN_PB{i}", 7.5, True)),
            Paragraph(f"{pr.km_total:,.0f}".replace(",", "."), _ps(f"AN_PKT{i}", 7.5, color=C_ACCENT)),
            Paragraph(f"{r['ep20']:.2f} EUR", _ps(f"AN_PR1{i}", 7)),
            Paragraph(f"{r['ep21']:.2f} EUR", _ps(f"AN_PR2{i}", 7)),
            Paragraph(f"<b>{_fmt_eur(pr.ep)}</b>", _ps(f"AN_PE{i}", 8, True, C_GREEN, TA_RIGHT)),
        ])

    # Total row
    ep_data.append([
        Paragraph("<b>GESAMT</b>", _ps("AN_GT", 8, True, C_WHITE, TA_LEFT)),
        Paragraph("", hs),
        Paragraph(f"<b>{wk.total_buero}</b>", _ps("AN_GTB", 8, True, C_WHITE)),
        Paragraph(f"<b>{wk.total_km:,.0f}</b>".replace(",", "."), _ps("AN_GTK", 8, True, C_WHITE)),
        Paragraph("", hs), Paragraph("", hs),
        Paragraph(f"<b>{_fmt_eur(wk.total_ep)}</b>", _ps("AN_GTE", 9, True, C_WHITE, TA_RIGHT)),
    ])

    cw = pw / 7
    ep_tbl = Table(ep_data, colWidths=[cw * 1.3, cw * 0.9, cw * 0.8, cw * 1.1, cw * 0.9, cw * 0.9, cw * 1.1])
    ep_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HDR),
        ("BACKGROUND", (0, len(ep_data) - 1), (-1, -1), C_HDR2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BOX", (0, 0), (-1, -1), 0.5, C_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(ep_data) - 1):
        if i % 2 == 0:
            ep_style.append(("BACKGROUND", (0, i), (-1, i), C_FAINT))
    ep_tbl.setStyle(TableStyle(ep_style))

    elements.append(Paragraph("<b>1. Entfernungspauschale</b> (Anlage N, Zeile 31-35)",
                              _ps("AN_S1", 10, True, C_DARK, TA_LEFT)))
    elements.append(Spacer(1, 2 * mm))
    elements.append(ep_tbl)
    elements.append(Spacer(1, 6 * mm))

    # --- Section 2: Homeoffice-Pauschale ---
    elements.append(Paragraph("<b>2. Homeoffice-Pauschale</b> (Anlage N, Zeile 44)",
                              _ps("AN_S2", 10, True, C_DARK, TA_LEFT)))
    elements.append(Spacer(1, 2 * mm))

    ho_data = [
        [Paragraph(h, hs) for h in [
            "Home-Office-Tage", "Tagessatz", "Max. Tage", "Anrechenbare Tage", "Pauschale"]],
        [
            Paragraph(f"<b>{wk.total_ho}</b>", _ps("AN_HOT", 9, True)),
            Paragraph(f"{wk.ho_rate:.2f} EUR".replace(".", ","), _ps("AN_HOR", 8)),
            Paragraph(str(wk.ho_cap), _ps("AN_HOC", 8, color=C_MID)),
            Paragraph(f"<b>{wk.ho_capped}</b>", _ps("AN_HOA", 9, True,
                      C_ORANGE if wk.total_ho > wk.ho_cap else C_DARK)),
            Paragraph(f"<b>{_fmt_eur(wk.ho_pauschale)}</b>", _ps("AN_HOP", 9, True, C_GREEN, TA_RIGHT)),
        ],
    ]
    ho_tbl = Table(ho_data, colWidths=[pw * 0.2] * 5)
    ho_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_HDR),
        ("BACKGROUND", (0, 1), (-1, 1), C_FAINT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BOX", (0, 0), (-1, -1), 0.5, C_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(ho_tbl)
    elements.append(Spacer(1, 6 * mm))

    # --- Section 3: Summary ---
    elements.append(Paragraph("<b>3. Zusammenfassung Werbungskosten</b>",
                              _ps("AN_S3", 10, True, C_DARK, TA_LEFT)))
    elements.append(Spacer(1, 2 * mm))

    sum_rows = [
        [Paragraph("Position", hs), Paragraph("Betrag", hs)],
        [Paragraph("Entfernungspauschale", _ps("AN_Z1", 8, color=C_DARK, align=TA_LEFT)),
         Paragraph(f"<b>{_fmt_eur(wk.total_ep)}</b>", _ps("AN_Z1V", 9, True, C_DARK, TA_RIGHT))],
        [Paragraph("Homeoffice-Pauschale", _ps("AN_Z2", 8, color=C_DARK, align=TA_LEFT)),
         Paragraph(f"<b>{_fmt_eur(wk.ho_pauschale)}</b>", _ps("AN_Z2V", 9, True, C_DARK, TA_RIGHT))],
    ]
    # Total
    sum_rows.append([
        Paragraph("<b>Werbungskosten gesamt</b>", _ps("AN_ZT", 10, True, C_WHITE, TA_LEFT)),
        Paragraph(f"<b>{_fmt_eur(wk.werbungskosten_total)}</b>",
                  _ps("AN_ZTV", 12, True, C_WHITE, TA_RIGHT)),
    ])
    # Comparison
    comparison_color = C_GREEN if wk.above_pauschbetrag else C_RED_SOFT
    sum_rows.append([
        Paragraph(f"Werbungskostenpauschbetrag {wk.year}", _ps("AN_ZP", 8, color=C_MID, align=TA_LEFT)),
        Paragraph(f"{_fmt_eur(wk.pauschbetrag)}", _ps("AN_ZPV", 8, color=C_MID, align=TA_RIGHT)),
    ])
    verdict = "Einzelnachweis lohnt sich!" if wk.above_pauschbetrag else "Pauschbetrag ist günstiger."
    sum_rows.append([
        Paragraph(f"<b>{verdict}</b>",
                  _ps("AN_ZV", 9, True, comparison_color, TA_LEFT)),
        Paragraph(f"<b>Vorteil: {_fmt_eur(wk.net_benefit)}</b>" if wk.above_pauschbetrag
                  else "", _ps("AN_ZVV", 9, True, C_GREEN, TA_RIGHT)),
    ])

    sum_tbl = Table(sum_rows, colWidths=[pw * 0.6, pw * 0.4])
    sum_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HDR),
        ("BACKGROUND", (0, 3), (-1, 3), C_HDR2),
        ("BACKGROUND", (0, 4), (-1, 4), C_FAINT),
        ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#EBF5FB") if wk.above_pauschbetrag
         else colors.HexColor("#FDEDEC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, C_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in (1, 2):
        if i % 2 == 0:
            sum_style.append(("BACKGROUND", (0, i), (-1, i), C_FAINT))
    sum_tbl.setStyle(TableStyle(sum_style))
    elements.append(sum_tbl)
    elements.append(Spacer(1, 6 * mm))

    # Disclaimer
    elements.append(Paragraph(
        "<i>Alle Angaben ohne Gewähr. Bitte prüfen Sie die Werte mit Ihrem Steuerberater "
        "oder der aktuellen ELSTER-Dokumentation.</i>",
        _ps("AN_DISC", 7, color=C_MID, align=TA_LEFT, lead=10)))

    return elements
