#!/usr/bin/env python3
"""
Arbeitstage-Kalender Generator
Generates print-ready PDF annual work calendars for German tax documentation.
Uses feiertage-api.de for public holiday data with local fallback.
Supports multi-period years (mid-year address/km changes).
"""

import json
import datetime
import calendar
import os
import sys
import urllib.request
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image,
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.lib.utils import ImageReader

from models import (
    PersonalData, YearConfig, PeriodConfig,
    load_metadata, parse_workdays, parse_ho, parse_km, LAND_CODES,
)

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
C_BUERO    = colors.HexColor("#FFFFFF")
C_HO       = colors.HexColor("#CEEBFD")
C_URLAUB   = colors.HexColor("#C8F7D5")
C_FEIER    = colors.HexColor("#FDE8CD")
C_WE       = colors.HexColor("#EAECEE")
C_HDR      = colors.HexColor("#1B2631")
C_HDR2     = colors.HexColor("#2C3E50")
C_ACCENT   = colors.HexColor("#2980B9")
C_DARK     = colors.HexColor("#1B2631")
C_MID      = colors.HexColor("#5D6D7E")
C_LIGHT    = colors.HexColor("#D5D8DC")
C_FAINT    = colors.HexColor("#F2F3F4")
C_WHITE    = colors.HexColor("#FFFFFF")
C_GREEN    = colors.HexColor("#27AE60")
C_ORANGE   = colors.HexColor("#E67E22")
C_BLUE2    = colors.HexColor("#2E86C1")
C_BLUE_L   = colors.HexColor("#85C1E9")
C_AMBER_L  = colors.HexColor("#F0B27A")
C_RED_D    = colors.HexColor("#A04000")
C_FEIER_ALT = colors.HexColor("#FDF2E9")

WT_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE  = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
           "Juli", "August", "September", "Oktober", "November", "Dezember"]
MON3    = ["", "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
           "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


class T:
    B = "Büro"
    H = "Home-Office"
    U = "Urlaub"
    F = "Feiertag"
    W = "Wochenende"


COLORS = {T.B: C_BUERO, T.H: C_HO, T.U: C_URLAUB, T.F: C_FEIER, T.W: C_WE}


# ---------------------------------------------------------------------------
# Feiertage
# ---------------------------------------------------------------------------
def _easter(y):
    a = y % 19; b, c = divmod(y, 100); d, e = divmod(b, 4)
    f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4)
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return datetime.date(y, month, day + 1)


def _local_feiertage(year, lc):
    e = _easter(year)
    hol = {
        datetime.date(year, 1, 1): "Neujahrstag",
        e - datetime.timedelta(2): "Karfreitag",
        e + datetime.timedelta(1): "Ostermontag",
        datetime.date(year, 5, 1): "Tag der Arbeit",
        e + datetime.timedelta(39): "Christi Himmelfahrt",
        e + datetime.timedelta(50): "Pfingstmontag",
        datetime.date(year, 10, 3): "Tag der Dt. Einheit",
        datetime.date(year, 12, 25): "1. Weihnachtstag",
        datetime.date(year, 12, 26): "2. Weihnachtstag",
    }
    if lc in ("BW","BY","ST"): hol[datetime.date(year,1,6)] = "Hl. Drei Könige"
    if lc in ("BE","MV"): hol[datetime.date(year,3,8)] = "Int. Frauentag"
    if lc in ("BW","BY","HE","NW","RP","SL"): hol[e+datetime.timedelta(60)] = "Fronleichnam"
    if lc in ("BY","SL"): hol[datetime.date(year,8,15)] = "Mariä Himmelfahrt"
    if lc == "TH": hol[datetime.date(year,9,20)] = "Weltkindertag"
    if lc in ("BB","HB","HH","MV","NI","SN","ST","SH","TH"):
        hol[datetime.date(year,10,31)] = "Reformationstag"
    if lc in ("BW","BY","NW","RP","SL"): hol[datetime.date(year,11,1)] = "Allerheiligen"
    if lc == "SN":
        n = datetime.date(year,11,23)
        hol[n - datetime.timedelta((n.weekday()-2)%7)] = "Buß- und Bettag"
    return hol


def fetch_feiertage(year, bundesland):
    lc = LAND_CODES.get(bundesland.lower())
    if not lc:
        print(f"Unbekanntes Bundesland: {bundesland}"); sys.exit(1)
    url = f"https://feiertage-api.de/api/?jahr={year}&nur_land={lc}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Arbeitstage/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        hol = {datetime.date.fromisoformat(v["datum"]): k for k, v in raw.items()}
        print(f"  Feiertage via API: {url}")
        return hol
    except Exception as exc:
        print(f"  API-Fallback ({exc}), lokale Berechnung.")
        return _local_feiertage(year, lc)


# ---------------------------------------------------------------------------
# Classify days (multi-period aware)
# ---------------------------------------------------------------------------
def classify(year, feiertage, yc: YearConfig):
    """Classify every day using period-specific workday/HO config."""
    r = {}
    d = datetime.date(year, 1, 1)
    while d <= datetime.date(year, 12, 31):
        period = yc.period_for_date(d)
        wd = d.weekday()
        if d in feiertage:
            r[d] = (T.F, feiertage[d])
        elif wd not in period.workdays:
            r[d] = (T.W, "")
        elif wd in period.ho_days:
            r[d] = (T.H, "")
        else:
            r[d] = (T.B, "")
        d += datetime.timedelta(1)

    if yc.total_urlaub > 0:
        r = _allocate_urlaub(year, r, feiertage, yc.total_urlaub)
    return r


def _is_workday(d, r):
    return r.get(d, (None,))[0] in (T.B, T.H)


def _find_brueckentage(year, feiertage, r):
    candidates = []
    for ft_date in sorted(feiertage.keys()):
        wd = ft_date.weekday()
        if wd == 3:
            bridge = ft_date + datetime.timedelta(1)
            if _is_workday(bridge, r):
                candidates.append((bridge, f"Brückentag ({feiertage[ft_date]})"))
        elif wd == 1:
            bridge = ft_date - datetime.timedelta(1)
            if _is_workday(bridge, r):
                candidates.append((bridge, f"Brückentag ({feiertage[ft_date]})"))
        elif wd == 2:
            thu = ft_date + datetime.timedelta(1)
            fri = ft_date + datetime.timedelta(2)
            mon = ft_date - datetime.timedelta(2)
            tue = ft_date - datetime.timedelta(1)
            if _is_workday(thu, r) and _is_workday(fri, r):
                candidates.append((thu, f"Brückentag ({feiertage[ft_date]})"))
                candidates.append((fri, f"Brückentag ({feiertage[ft_date]})"))
            elif _is_workday(mon, r) and _is_workday(tue, r):
                candidates.append((mon, f"Brückentag ({feiertage[ft_date]})"))
                candidates.append((tue, f"Brückentag ({feiertage[ft_date]})"))
    return candidates


def _find_christmas_block(year, r):
    candidates = []
    for day in range(23, 32):
        try:
            d = datetime.date(year, 12, day)
        except ValueError:
            break
        if _is_workday(d, r):
            candidates.append((d, "Weihnachtsurlaub"))
    for day in range(2, 6):
        d = datetime.date(year, 1, day)
        if _is_workday(d, r):
            candidates.append((d, "Neujahrsurlaub"))
    return candidates


def _allocate_urlaub(year, r, feiertage, urlaub_count):
    remaining = urlaub_count
    allocated = []
    for d, label in _find_brueckentage(year, feiertage, r):
        if remaining <= 0: break
        if _is_workday(d, r):
            r[d] = (T.U, label); remaining -= 1; allocated.append(d)
    for d, label in _find_christmas_block(year, r):
        if remaining <= 0: break
        if _is_workday(d, r):
            r[d] = (T.U, label); remaining -= 1; allocated.append(d)
    r["_urlaub_remaining"] = remaining
    r["_urlaub_allocated"] = len(allocated)
    return r


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def mstats(year, month, dm):
    s = {T.B: 0, T.H: 0, T.F: 0, T.W: 0, T.U: 0}
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        s[dm[datetime.date(year, month, day)][0]] += 1
    return s


def astats(year, dm):
    s = {T.B: 0, T.H: 0, T.F: 0, T.W: 0, T.U: 0, "fw": 0}
    d = datetime.date(year, 1, 1)
    while d <= datetime.date(year, 12, 31):
        dt = dm[d][0]; s[dt] = s.get(dt, 0) + 1
        if dt == T.F and d.weekday() < 5: s["fw"] += 1
        d += datetime.timedelta(1)
    s["u_remaining"] = dm.get("_urlaub_remaining", 0)
    s["u_allocated"] = dm.get("_urlaub_allocated", 0)
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ps(name, sz=7.5, bold=False, color=C_DARK, align=TA_CENTER, lead=None):
    return ParagraphStyle(
        name, fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=sz, leading=lead or sz + 2, textColor=color, alignment=align)


def _fmt_eur(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def _scaled_image(path, max_w, max_h):
    """Create an Image that preserves aspect ratio within max bounds."""
    try:
        ir = ImageReader(path)
        iw, ih = ir.getSize()
        ratio = min(max_w / iw, max_h / ih)
        img = Image(path, width=iw * ratio, height=ih * ratio)
        img.hAlign = "LEFT"
        return img
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def generate(metadata_path, output_path=None):
    """Legacy entry point: generate all years from metadata.json."""
    personal, year_configs = load_metadata(metadata_path)
    base_dir = str(Path(metadata_path).parent)

    for yc in year_configs:
        out = output_path or str(Path(base_dir) / f"Arbeitstage_{yc.year}_{yc.bundesland}.pdf")
        generate_year(yc, personal, base_dir, out)


def generate_year(yc: YearConfig, personal: PersonalData, base_dir: str,
                  output_path: str, include_anlage_n: bool = False,
                  verbose: bool = False):
    """Generate PDF for one year."""
    year = yc.year
    print(f"Generiere {year} ({yc.bundesland})...")

    feiertage = fetch_feiertage(year, yc.bundesland)
    dm = classify(year, feiertage, yc)
    ann = astats(year, dm)

    # Resolve map paths per period
    for p in yc.periods:
        if p.map_file:
            full = os.path.join(base_dir, p.map_file)
            p.map_file = full if os.path.isfile(full) else ""

    # Compute Werbungskosten
    from tax_summary import compute_werbungskosten, entfernungspauschale, homeoffice_pauschale
    wk = compute_werbungskosten(year, yc, dm)

    _build_pdf(year, yc, personal, dm, feiertage, ann, wk, output_path, include_anlage_n)
    print(f"  PDF erstellt: {output_path}")


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------
def _build_pdf(year, yc: YearConfig, personal: PersonalData, dm, feiertage, ann,
               wk, path, include_anlage_n):
    from tax_summary import render_anlage_n_page

    doc = SimpleDocTemplate(
        path, pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=10*mm, bottomMargin=10*mm,
        title=f"Arbeitstage {year}", author="Tax-Automate-Germany",
    )
    pw = landscape(A4)[0] - 20*mm

    el = []
    multi = len(yc.periods) > 1

    # ========== PAGE 1: Cover ==========
    el.append(Spacer(1, 3*mm))
    name = personal.full_name
    _add_title_bar(el, f"ARBEITSTAGE-KALENDER {year}",
                   f"{yc.bundesland} ({yc.land_code})" + (f"  |  {name}" if name else ""), pw)
    el.append(Spacer(1, 3*mm))

    # --- Three-column cover ---
    col_w = pw / 3 - 2*mm

    # COL 1: Personal + Config
    c1 = _cover_col1(personal, yc, col_w)

    # COL 2: Tax figures + Fahrt
    c2 = _cover_col2(ann, yc, wk, col_w, year)

    # COL 3: Feiertage + Addresses
    c3 = _cover_col3(feiertage, yc, col_w)

    outer = Table([[c1, c2, c3]], colWidths=[col_w + 2*mm]*3)
    outer.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 2),
    ]))
    el.append(outer)
    el.append(Spacer(1, 3*mm))

    # Route map(s) + comment
    _add_map_section(el, yc, pw)

    # Legend + footer
    el.append(_legend(pw))
    el.append(Spacer(1, 2*mm))
    el.append(Paragraph(
        f'Erstellt am {datetime.date.today().strftime("%d.%m.%Y")} | '
        f'Steuerjahr {year} | Quelle: feiertage-api.de',
        _ps("FT_cov", 6.5, color=C_MID)))
    el.append(PageBreak())

    # ========== PAGES 2-3: Grid calendars ==========
    for start in (1, 7):
        _add_title_bar(el, f"MONATSKALENDER {year}",
                       f"{MON3[start]}-{MON3[min(start+5,12)]}  |  {yc.bundesland}", pw)
        el.append(Spacer(1, 2*mm))
        el.append(_month_grids(year, dm, feiertage, list(range(start, min(start+6, 13))), pw))
        el.append(Spacer(1, 2*mm))
        el.append(_legend(pw))
        if start == 1:
            el.append(PageBreak())
    el.append(PageBreak())

    # ========== PAGE 4: Summary ==========
    _add_title_bar(el, f"JAHRESÜBERSICHT {year}", yc.bundesland, pw)
    el.append(Spacer(1, 3*mm))
    el.append(_summary_table(year, dm, yc, pw))
    el.append(Spacer(1, 4*mm))
    el.append(_chart(year, dm))
    el.append(Spacer(1, 4*mm))
    el.append(Paragraph(
        f'Erstellt am {datetime.date.today().strftime("%d.%m.%Y")} | '
        f'Erstellt für Steuerjahr {year}',
        _ps("FT_sum", 6.5, color=C_MID)))

    # ========== PAGE 5 (optional): Anlage N ==========
    if include_anlage_n:
        el.append(PageBreak())
        el.extend(render_anlage_n_page(wk, pw))

    doc.build(el)


# ---------------------------------------------------------------------------
# Cover column builders
# ---------------------------------------------------------------------------
def _cover_col1(personal: PersonalData, yc: YearConfig, w):
    """Personal data + work configuration."""
    rows = []
    rows.append([Paragraph("<b>Persönliche Daten</b>", _ps("c1h", 8, True, C_WHITE, TA_LEFT)), ""])
    if personal.full_name:
        rows.append([Paragraph("Name", _ps("c1_n", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(f"<b>{personal.full_name}</b>", _ps("c1_nv", 7, True, C_DARK, TA_LEFT))])
    if personal.geburtsdatum:
        rows.append([Paragraph("Geb.datum", _ps("c1_g", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(personal.geburtsdatum, _ps("c1_gv", 7, color=C_DARK, align=TA_LEFT))])
    if personal.steuer_id:
        rows.append([Paragraph("Steuer-ID", _ps("c1_s", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(personal.steuer_id, _ps("c1_sv", 7, color=C_DARK, align=TA_LEFT))])
    if personal.finanzamt:
        rows.append([Paragraph("Finanzamt", _ps("c1_f", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(personal.finanzamt, _ps("c1_fv", 7, color=C_DARK, align=TA_LEFT))])
    if personal.steuerklasse:
        rows.append([Paragraph("Steuerklasse", _ps("c1_k", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(personal.steuerklasse, _ps("c1_kv", 7, color=C_DARK, align=TA_LEFT))])

    # Work config per period
    for pi, p in enumerate(yc.periods):
        label = f"Arbeitskonfiguration" if len(yc.periods) == 1 else f"Konfiguration {p.label}"
        rows.append([Paragraph(f"<b>{label}</b>", _ps(f"c1_ch{pi}", 8, True, C_WHITE, TA_LEFT)), ""])
        rows.append([Paragraph("Arbeitstage", _ps(f"c1_at{pi}", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(f"<b>{p.work_label}</b>", _ps(f"c1_atv{pi}", 7, True, C_DARK, TA_LEFT))])
        rows.append([Paragraph("Home-Office", _ps(f"c1_ho{pi}", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(f"<b>{p.ho_label}</b>", _ps(f"c1_hov{pi}", 7, True, C_ACCENT, TA_LEFT))])
        rows.append([Paragraph("Entfernung", _ps(f"c1_km{pi}", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(f"<b>{p.km:.0f} km</b>", _ps(f"c1_kmv{pi}", 7, True, C_DARK, TA_LEFT))])

    rows.append([Paragraph("Urlaubstage", _ps("c1_u", 7, color=C_MID, align=TA_LEFT)),
                 Paragraph(f"<b>{yc.total_urlaub} Tage</b>", _ps("c1_uv", 7, True, C_GREEN, TA_LEFT))])

    tbl = Table(rows, colWidths=[w*0.38, w*0.62])
    style = [
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 1.5), ("BOTTOMPADDING", (0,0), (-1,-1), 1.5),
        ("LEFTPADDING", (0,0), (-1,-1), 3), ("BOX", (0,0), (-1,-1), 0.5, C_LIGHT),
    ]
    # Style headers and alternating rows
    for i, row in enumerate(rows):
        if isinstance(row[1], str) and row[1] == "":
            style.append(("SPAN", (0, i), (1, i)))
            style.append(("BACKGROUND", (0, i), (-1, i), C_HDR2))
        elif i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C_FAINT))
    tbl.setStyle(TableStyle(style))
    return tbl


def _cover_col2(ann, yc: YearConfig, wk, w, year):
    """Tax figures + Fahrt calculation."""
    buero = ann[T.B]
    ho = ann[T.H]
    arbeit = buero + ho

    rows = [
        [Paragraph("<b>Steuerrelevante Kennzahlen</b>", _ps("c2h", 8, True, C_WHITE, TA_LEFT)), ""],
        [Paragraph("Bürotage", _ps("c2_bt", 7, color=C_MID, align=TA_LEFT)),
         Paragraph(f"<b>{buero}</b>", _ps("c2_btv", 11, True, C_ACCENT, TA_RIGHT))],
        [Paragraph("Home-Office-Tage", _ps("c2_ho", 7, color=C_MID, align=TA_LEFT)),
         Paragraph(f"<b>{ho}</b>", _ps("c2_hov", 11, True, C_BLUE2, TA_RIGHT))],
        [Paragraph("Arbeitstage gesamt", _ps("c2_at", 7, color=C_MID, align=TA_LEFT)),
         Paragraph(f"<b>{arbeit}</b>", _ps("c2_atv", 11, True, C_DARK, TA_RIGHT))],
        [Paragraph("Feiertage (Werktag)", _ps("c2_ft", 7, color=C_MID, align=TA_LEFT)),
         Paragraph(f"<b>{ann['fw']}</b>", _ps("c2_ftv", 11, True, C_ORANGE, TA_RIGHT))],
        [Paragraph("Urlaubstage geplant", _ps("c2_ur", 7, color=C_MID, align=TA_LEFT)),
         Paragraph(f"<b>{ann.get(T.U, 0)}</b> / {yc.total_urlaub}",
                   _ps("c2_urv", 9, True, C_GREEN, TA_RIGHT))],
        [Paragraph("davon frei planbar", _ps("c2_uf", 7, color=C_MID, align=TA_LEFT)),
         Paragraph(f"<b>{ann.get('u_remaining', 0)}</b>", _ps("c2_ufv", 9, True, C_MID, TA_RIGHT))],
    ]

    # Fahrt section - show per-period if multi
    rows.append([Paragraph("<b>Fahrtkostenberechnung</b>", _ps("c2_fh", 8, True, C_WHITE, TA_LEFT)), ""])

    if len(wk.periods) > 1:
        for i, pr in enumerate(wk.periods):
            rows.append([
                Paragraph(f"{pr.label} ({pr.km:.0f} km)", _ps(f"c2_fp{i}", 6.5, color=C_MID, align=TA_LEFT)),
                Paragraph(f"<b>{_fmt_eur(pr.ep)}</b>", _ps(f"c2_fpv{i}", 7, True, C_DARK, TA_RIGHT)),
            ])
    else:
        pr = wk.periods[0]
        rows.append([Paragraph("Einfache Entfernung", _ps("c2_km", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(f"<b>{pr.km:.0f} km</b>", _ps("c2_kmv", 8, True, C_DARK, TA_RIGHT))])
        rows.append([Paragraph("Fahrten (= Bürotage)", _ps("c2_fb", 7, color=C_MID, align=TA_LEFT)),
                     Paragraph(f"<b>{buero}</b>", _ps("c2_fbv", 8, True, C_DARK, TA_RIGHT))])

    rows.append([Paragraph("Entfernungspauschale", _ps("c2_ep", 7, color=C_MID, align=TA_LEFT)),
                 Paragraph(f"<b>{_fmt_eur(wk.total_ep)}</b>", _ps("c2_epv", 9, True, C_GREEN, TA_RIGHT))])
    rows.append([Paragraph("Homeoffice-Pauschale", _ps("c2_hp", 7, color=C_MID, align=TA_LEFT)),
                 Paragraph(f"<b>{_fmt_eur(wk.ho_pauschale)}</b>", _ps("c2_hpv", 9, True, C_ACCENT, TA_RIGHT))])
    rows.append([Paragraph("<b>Werbungskosten ges.</b>", _ps("c2_wk", 7, True, C_MID, align=TA_LEFT)),
                 Paragraph(f"<b>{_fmt_eur(wk.werbungskosten_total)}</b>",
                           _ps("c2_wkv", 10, True, C_GREEN, TA_RIGHT))])

    tbl = Table(rows, colWidths=[w*0.55, w*0.45])
    style = [
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 1.5), ("BOTTOMPADDING", (0,0), (-1,-1), 1.5),
        ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (-1,0), (-1,-1), 3),
        ("BOX", (0,0), (-1,-1), 0.5, C_LIGHT),
    ]
    for i, row in enumerate(rows):
        if isinstance(row[1], str) and row[1] == "":
            style.append(("SPAN", (0, i), (1, i)))
            style.append(("BACKGROUND", (0, i), (-1, i), C_HDR2))
        elif i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C_FAINT))
    tbl.setStyle(TableStyle(style))
    return tbl


def _cover_col3(feiertage, yc: YearConfig, w):
    """Feiertage list + addresses per period."""
    rows = [
        [Paragraph("<b>Feiertage</b>", _ps("c3h", 8, True, C_WHITE, TA_LEFT)),
         Paragraph(f"<b>{yc.bundesland}</b>", _ps("c3h2", 7, True, C_BLUE_L, TA_RIGHT))],
    ]
    for d in sorted(feiertage.keys()):
        on_wd = d.weekday() < 5
        rows.append([
            Paragraph(f"<b>{d.strftime('%d.%m.')}</b> {WT_KURZ[d.weekday()]}",
                      _ps(f"c3d{d.toordinal()}", 6.5, color=C_DARK if on_wd else C_MID, align=TA_LEFT)),
            Paragraph(f"{feiertage[d]}" + ("" if on_wd else " <i>(WE)</i>"),
                      _ps(f"c3n{d.toordinal()}", 6.5, color=C_RED_D if on_wd else C_MID, align=TA_LEFT)),
        ])

    # Addresses per period
    for pi, p in enumerate(yc.periods):
        label = "Adressen" if len(yc.periods) == 1 else f"Adressen {p.label}"
        rows.append([Paragraph(f"<b>{label}</b>", _ps(f"c3ah{pi}", 8, True, C_WHITE, TA_LEFT)), ""])
        if p.addr_home:
            rows.append([Paragraph("Wohnung", _ps(f"c3w{pi}", 6.5, color=C_MID, align=TA_LEFT)),
                         Paragraph(p.addr_home, _ps(f"c3wv{pi}", 6.5, color=C_DARK, align=TA_LEFT))])
        if p.addr_work:
            rows.append([Paragraph("Arbeit", _ps(f"c3a{pi}", 6.5, color=C_MID, align=TA_LEFT)),
                         Paragraph(p.addr_work, _ps(f"c3av{pi}", 6.5, color=C_DARK, align=TA_LEFT))])

    tbl = Table(rows, colWidths=[w*0.30, w*0.70])
    style = [
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 1.5), ("BOTTOMPADDING", (0,0), (-1,-1), 1.5),
        ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (-1,0), (-1,-1), 3),
        ("BOX", (0,0), (-1,-1), 0.5, C_LIGHT),
    ]
    ft_count = len(feiertage)
    for i, row in enumerate(rows):
        if isinstance(row[1], str) and row[1] == "":
            style.append(("SPAN", (0, i), (1, i)))
            style.append(("BACKGROUND", (0, i), (-1, i), C_HDR2))
        elif i <= ft_count:
            style.append(("BACKGROUND", (0, i), (-1, i), C_FEIER if i % 2 == 0 else C_FEIER_ALT))
        elif i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C_FAINT))
    tbl.setStyle(TableStyle(style))
    return tbl


# ---------------------------------------------------------------------------
# Map section (aspect-ratio preserving)
# ---------------------------------------------------------------------------
def _add_map_section(el, yc: YearConfig, pw):
    """Add route map(s) with preserved aspect ratio and period comments."""
    # Collect unique maps with their comments
    maps = []
    seen_files = set()
    for p in yc.periods:
        if p.map_file and p.map_file not in seen_files:
            maps.append((p.map_file, p.kommentar, p.label))
            seen_files.add(p.map_file)
        elif not p.map_file and p.kommentar:
            maps.append(("", p.kommentar, p.label))

    if not maps:
        return

    if len(maps) == 1:
        # Single map: wide layout
        mf, comment, label = maps[0]
        header = [
            Paragraph("<b>Fahrtroute</b>", _ps("mrh1", 8, True, C_WHITE, TA_LEFT)),
            Paragraph("<b>Anmerkung</b>", _ps("mrh2", 8, True, C_WHITE, TA_LEFT)),
        ]
        img = _scaled_image(mf, 130*mm, 55*mm) if mf else ""
        comment_p = Paragraph(f'<i>"{comment}"</i>', _ps("mrc", 7, color=C_MID, align=TA_LEFT, lead=10)) if comment else ""
        data = [header, [img or "", comment_p]]
        tbl = Table(data, colWidths=[pw*0.52, pw*0.48])
    else:
        # Multiple maps side by side
        header = []
        img_row = []
        for i, (mf, comment, label) in enumerate(maps):
            header.append(Paragraph(f"<b>Route: {label}</b>", _ps(f"mrh{i}", 8, True, C_WHITE, TA_LEFT)))
            cell_w = pw / len(maps) - 4*mm
            img = _scaled_image(mf, cell_w, 50*mm) if mf else ""
            # Stack image + comment in a sub-table
            sub_rows = []
            if img: sub_rows.append([img])
            if comment:
                sub_rows.append([Paragraph(f'<i>"{comment}"</i>',
                                 _ps(f"mrc{i}", 6.5, color=C_MID, align=TA_LEFT, lead=9))])
            if sub_rows:
                sub = Table(sub_rows, colWidths=[cell_w])
                sub.setStyle(TableStyle([
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("TOPPADDING", (0,0), (-1,-1), 1), ("BOTTOMPADDING", (0,0), (-1,-1), 1),
                    ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0),
                ]))
                img_row.append(sub)
            else:
                img_row.append("")
        data = [header, img_row]
        cw = pw / len(maps)
        tbl = Table(data, colWidths=[cw]*len(maps))

    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), C_HDR2),
        ("BACKGROUND", (0,1), (-1,-1), C_FAINT),
        ("BOX", (0,0), (-1,-1), 0.5, C_LIGHT),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING", (0,0), (-1,-1), 3),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 2*mm))


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------
def _add_title_bar(el, title, subtitle, pw):
    data = [[
        Paragraph(f"<b>{title}</b>", _ps("tb_t", 14, True, C_WHITE, TA_LEFT)),
        Paragraph(f"<b>{subtitle}</b>", _ps("tb_s", 9, True, C_BLUE_L, TA_RIGHT)),
    ]]
    tbl = Table(data, colWidths=[pw*0.6, pw*0.4])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_HDR),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (0,0), 5), ("RIGHTPADDING", (-1,-1), (-1,-1), 5),
    ]))
    el.append(tbl)


def _legend(pw):
    items = [(C_BUERO, "Büro"), (C_HO, "Home-Office"), (C_URLAUB, "Urlaub"),
             (C_FEIER, "Feiertag"), (C_WE, "Wochenende")]
    cells = [Paragraph(lb, _ps(f"lg_{i}", 7, color=C_DARK)) for i, (_, lb) in enumerate(items)]
    cw = pw / len(items)
    tbl = Table([cells], colWidths=[cw]*len(items))
    cmds = [("BOX", (0,0), (-1,-1), 0.5, C_LIGHT),
            ("INNERGRID", (0,0), (-1,-1), 0.5, C_LIGHT),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2)]
    for i, (bg, _) in enumerate(items):
        cmds.append(("BACKGROUND", (i,0), (i,0), bg))
    tbl.setStyle(TableStyle(cmds))
    return tbl


# ---------------------------------------------------------------------------
# Grid calendars
# ---------------------------------------------------------------------------
def _month_grids(year, dm, feiertage, months, pw):
    ncol = 3; gap = 3*mm
    bw = (pw - gap*(ncol-1)) / ncol
    rows = []
    for rs in range(0, len(months), ncol):
        rm = months[rs:rs+ncol]
        cells = [_one_month(year, m, dm, feiertage, bw) for m in rm]
        while len(cells) < ncol: cells.append("")
        rows.append(cells)
    tbl = Table(rows, colWidths=[(bw + gap/ncol)]*ncol)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 1), ("BOTTOMPADDING", (0,0), (-1,-1), 1),
        ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 1),
    ]))
    return tbl


def _one_month(year, month, dm, feiertage, bw):
    kw_w = bw * 0.09; day_w = (bw - kw_w) / 7
    ms = mstats(year, month, dm)
    u_count = ms.get(T.U, 0)
    summary = f"B:{ms[T.B]} H:{ms[T.H]} F:{ms[T.F]}" + (f" U:{u_count}" if u_count else "")

    hdr = [Paragraph(f"<b>{MONATE[month]} {year}</b>", _ps("mh", 8, True, C_WHITE, TA_LEFT))] \
          + [""]*6 + [Paragraph(summary, _ps("ms", 5.5, color=C_BLUE_L, align=TA_RIGHT))]
    dhdr = [Paragraph("<b>KW</b>", _ps("kh", 6, True, C_WHITE))] + \
           [Paragraph(f"<b>{d}</b>", _ps(f"dh_{d}", 6, True, C_WHITE)) for d in WT_KURZ]

    data = [hdr, dhdr]
    sc = [
        ("SPAN", (0,0), (6,0)),
        ("BACKGROUND", (0,0), (-1,0), C_HDR2),
        ("BACKGROUND", (0,1), (-1,1), C_HDR),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 1.2), ("BOTTOMPADDING", (0,0), (-1,-1), 1.2),
        ("LEFTPADDING", (0,0), (-1,-1), 1), ("RIGHTPADDING", (0,0), (-1,-1), 1),
        ("BOX", (0,0), (-1,-1), 0.5, C_LIGHT),
        ("LINEBELOW", (0,1), (-1,1), 0.5, C_HDR),
        ("LEFTPADDING", (0,0), (0,0), 3), ("RIGHTPADDING", (-1,0), (-1,0), 3),
    ]

    cal_obj = calendar.Calendar(firstweekday=0)
    for wi, week in enumerate(cal_obj.monthdayscalendar(year, month)):
        ri = wi + 2
        kw = ""
        for dn in week:
            if dn > 0:
                kw = datetime.date(year, month, dn).isocalendar()[1]; break
        row = [Paragraph(str(kw), _ps(f"k_{wi}", 5.5, color=C_MID))]
        for di, dn in enumerate(week):
            if dn == 0:
                row.append("")
                sc.append(("BACKGROUND", (di+1, ri), (di+1, ri), colors.HexColor("#FAFAFA")))
            else:
                d = datetime.date(year, month, dn)
                dt = dm[d][0]
                if dt == T.F:
                    row.append(Paragraph(f"<b>{dn}</b>", _ps(f"c_{dn}", 6.5, True, C_RED_D)))
                elif dt == T.U:
                    row.append(Paragraph(f"<b>{dn}</b>", _ps(f"c_{dn}", 6.5, True, C_GREEN)))
                elif dt == T.W:
                    row.append(Paragraph(str(dn), _ps(f"c_{dn}", 6, color=C_MID)))
                elif dt == T.H:
                    row.append(Paragraph(f"<b>{dn}</b>", _ps(f"c_{dn}", 6.5, True, C_ACCENT)))
                else:
                    row.append(Paragraph(str(dn), _ps(f"c_{dn}", 6, color=C_DARK)))
                sc.append(("BACKGROUND", (di+1, ri), (di+1, ri), COLORS[dt]))
        data.append(row)
        sc.append(("LINEBELOW", (0, ri), (-1, ri), 0.15, C_LIGHT))

    u_str = f"  <b>U</b>:{u_count}" if u_count else ""
    ft = [Paragraph(f"<b>B</b>:{ms[T.B]}  <b>H</b>:{ms[T.H]}  <b>F</b>:{ms[T.F]}  <b>W</b>:{ms[T.W]}{u_str}",
                    _ps("mf", 5.5, color=C_MID, align=TA_LEFT))] + [""]*7
    data.append(ft)
    fi = len(data) - 1
    sc.extend([
        ("SPAN", (0, fi), (-1, fi)),
        ("BACKGROUND", (0, fi), (-1, fi), C_FAINT),
        ("LINEABOVE", (0, fi), (-1, fi), 0.3, C_LIGHT),
        ("LEFTPADDING", (0, fi), (0, fi), 3),
    ])

    tbl = Table(data, colWidths=[kw_w] + [day_w]*7)
    tbl.setStyle(TableStyle(sc))
    return tbl


# ---------------------------------------------------------------------------
# Summary table (period-aware km)
# ---------------------------------------------------------------------------
def _summary_table(year, dm, yc: YearConfig, pw):
    cols = [pw*0.12] + [pw*0.065]*11 + [pw*0.065]
    hs = _ps("sh", 6.5, True, C_WHITE)
    vs = _ps("sv", 6.5)

    header = [Paragraph(h, hs) for h in [
        "Monat", "Büro", "HO", "Urlaub", "Arbeit", "Feiert.", "FT(WT)", "WE",
        "Kal.", "B-%", "H-%", "KW", "km(einf.)"]]
    data = [header]
    sc = [
        ("BACKGROUND", (0,0), (-1,0), C_HDR),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("BOX", (0,0), (-1,-1), 0.5, C_LIGHT),
        ("INNERGRID", (0,0), (-1,-1), 0.2, C_LIGHT),
        ("LEFTPADDING", (0,0), (-1,-1), 2), ("RIGHTPADDING", (0,0), (-1,-1), 2),
    ]
    tot = {k: 0 for k in "b h u a f fw w k km".split()}

    for m in range(1, 13):
        ms2 = mstats(year, m, dm)
        nd = calendar.monthrange(year, m)[1]
        at = ms2[T.B] + ms2[T.H]
        mu = ms2.get(T.U, 0)
        fw = sum(1 for d2 in range(1, nd+1) if dm[datetime.date(year,m,d2)][0] == T.F
                 and datetime.date(year,m,d2).weekday() < 5)
        bp = f"{ms2[T.B]/at*100:.0f}" if at else "0"
        hp = f"{ms2[T.H]/at*100:.0f}" if at else "0"
        kw1 = datetime.date(year,m,1).isocalendar()[1]
        kw2 = datetime.date(year,m,nd).isocalendar()[1]
        kws = f"{kw1}-{kw2}" if kw1 != kw2 else str(kw1)

        # km: sum per-day based on which period the day falls in
        m_km = 0.0
        for d2 in range(1, nd+1):
            dd = datetime.date(year, m, d2)
            if dm[dd][0] == T.B:
                m_km += yc.period_for_date(dd).km

        row = [
            Paragraph(f"<b>{MONATE[m]}</b>", _ps(f"sm_{m}", 6.5, True, C_DARK, TA_LEFT)),
            Paragraph(str(ms2[T.B]), vs), Paragraph(str(ms2[T.H]), vs),
            Paragraph(f"<b>{mu}</b>" if mu else "-",
                      _ps(f"su_{m}", 6.5, bold=mu > 0, color=C_GREEN if mu else C_MID)),
            Paragraph(f"<b>{at}</b>", _ps(f"sa_{m}", 6.5, True)),
            Paragraph(str(ms2[T.F]), vs), Paragraph(str(fw), vs),
            Paragraph(str(ms2[T.W]), vs), Paragraph(str(nd), vs),
            Paragraph(f"{bp}%", vs), Paragraph(f"{hp}%", vs),
            Paragraph(kws, _ps(f"skw_{m}", 6, color=C_MID)),
            Paragraph(f"{m_km:,.0f}".replace(",", "."), _ps(f"skm_{m}", 6.5, color=C_ACCENT)),
        ]
        data.append(row)
        ri = len(data) - 1
        if ri % 2 == 0:
            sc.append(("BACKGROUND", (0, ri), (-1, ri), C_FAINT))
        tot["b"] += ms2[T.B]; tot["h"] += ms2[T.H]; tot["u"] += mu; tot["a"] += at
        tot["f"] += ms2[T.F]; tot["fw"] += fw; tot["w"] += ms2[T.W]
        tot["k"] += nd; tot["km"] += m_km

    # Totals
    tbp = f"{tot['b']/tot['a']*100:.0f}" if tot["a"] else "0"
    thp = f"{tot['h']/tot['a']*100:.0f}" if tot["a"] else "0"
    ts = _ps("st", 7, True, C_WHITE)
    trow = [Paragraph(f"<b>{v}</b>", ts) for v in [
        "GESAMT", str(tot["b"]), str(tot["h"]), str(tot["u"]),
        str(tot["a"]), str(tot["f"]), str(tot["fw"]), str(tot["w"]),
        str(tot["k"]), f"{tbp}%", f"{thp}%", "1-52",
        f"{tot['km']:,.0f}".replace(",", ".")]]
    data.append(trow)
    tri = len(data) - 1
    sc.extend([
        ("BACKGROUND", (0, tri), (-1, tri), C_HDR),
        ("LINEABOVE", (0, tri), (-1, tri), 1, C_HDR),
    ])

    tbl = Table(data, colWidths=cols)
    tbl.setStyle(TableStyle(sc))
    return tbl


def _chart(year, dm):
    d = Drawing(700, 180)
    mb, mh, mf = [], [], []
    for m in range(1, 13):
        ms2 = mstats(year, m, dm)
        mb.append(ms2[T.B]); mh.append(ms2[T.H]); mf.append(ms2[T.F])
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 50, 20, 600, 135
    ch.data = [mb, mh, mf]
    ch.categoryAxis.categoryNames = [MON3[m] for m in range(1, 13)]
    ch.categoryAxis.labels.fontSize = 7
    ch.valueAxis.valueMin, ch.valueAxis.valueMax, ch.valueAxis.valueStep = 0, 25, 5
    ch.valueAxis.labels.fontSize = 7
    ch.bars[0].fillColor = colors.HexColor("#ABB2B9")
    ch.bars[1].fillColor = colors.HexColor("#5DADE2")
    ch.bars[2].fillColor = colors.HexColor("#F0B27A")
    for i in range(3): ch.bars[i].strokeColor = None
    ch.barSpacing, ch.groupSpacing = 1, 8
    d.add(ch)
    x = 200
    for lb, c in [("Büro","#ABB2B9"),("Home-Office","#5DADE2"),("Feiertag","#F0B27A")]:
        d.add(Rect(x, 163, 8, 8, fillColor=colors.HexColor(c), strokeColor=None))
        d.add(String(x+12, 164, lb, fontSize=7, fillColor=C_DARK))
        x += 90
    return d


# ---------------------------------------------------------------------------
# Legacy CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("Nutzung: python generate_calendar.py [metadata.json] [output.pdf]")
        print("Oder:    python cli.py --help")
        sys.exit(0)
    meta = sys.argv[1] if len(sys.argv) > 1 else "metadata.json"
    out = sys.argv[2] if len(sys.argv) > 2 else None
    personal, year_configs = load_metadata(meta)
    base_dir = str(Path(meta).parent)
    for yc in year_configs:
        yout = out or str(Path(base_dir) / f"Arbeitstage_{yc.year}_{yc.bundesland}.pdf")
        generate_year(yc, personal, base_dir, yout, include_anlage_n=True)
