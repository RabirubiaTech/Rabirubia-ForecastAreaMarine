#!/usr/bin/env python3
"""
Rabirubia Weather Card Generator
Fetches NWS San Juan marine forecasts and generates a daily Instagram-ready JPG.
Output is always saved as: output/marine_forecast.jpg  (fixed name for embedding)
"""

import os
import re
import sys
import json
import math
import base64
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request

# ─────────────────────────────────────────────
# NWS URLs
# ─────────────────────────────────────────────
NWS_COMBINED_URL  = "https://tgftp.nws.noaa.gov/data/raw/fz/fzca52.tjsj.cwf.sju.txt"
NWS_SYNOPSIS_URL  = "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz711.txt"
NWS_FORECAST_URL  = "https://api.weather.gov/gridpoints/SJU/60,77/forecast"

NWS_ZONES = {
    "atlantic":  "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz711.txt",
    "north_pr":  "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz712.txt",
    "east_pr":   "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz726.txt",
    "caribbean": "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz733.txt",
}

SCRIPT_DIR   = Path(__file__).parent
OUTPUT_DIR   = Path(os.environ.get("OUTPUT_DIR", SCRIPT_DIR.parent / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FIXED_OUTPUT = OUTPUT_DIR / "marine_forecast.jpg"
AST          = timezone(timedelta(hours=-4))   # Puerto Rico — no DST ever


# ─────────────────────────────────────────────
# Moon phase SVG icons
# Returns an inline <svg> string scaled to size
# ─────────────────────────────────────────────
def moon_svg(cycle_pos: float, size: int = 44) -> str:
    """
    Draw a moon disc using SVG.
    cycle_pos 0.0 = new moon, 0.5 = full moon, 1.0 = new moon again.
    The lit portion is shown in bright white/yellow; dark in dark navy.
    """
    r   = size // 2
    cx  = r
    cy  = r

    # Compute the terminator x-offset as a fraction of radius
    # At 0.0 (new): fully dark. At 0.5 (full): fully lit.
    # Waxing (0–0.5): left dark, right lit
    # Waning (0.5–1.0): left lit, right dark
    phase_angle = cycle_pos * 2 * math.pi
    illumination = (1 - math.cos(phase_angle)) / 2   # 0=new, 1=full

    lit   = "#F5E642"   # moon yellow
    dark  = "#0a1428"   # dark navy
    rim   = "#aaaaaa"   # thin rim

    # Draw background circle (dark side)
    # Then overlay the lit half using ellipse terminator
    # The terminator ellipse x-radius varies with phase:
    #   0.25 (first qtr) -> rx=0, full ellipse
    #   0.5 (full) -> entire circle lit
    #   0.75 (last qtr) -> rx=0, full ellipse

    if cycle_pos < 0.5:
        # Waxing: right side lit
        # Terminator rx: 0 at first quarter (0.25), max r at new/full
        t = abs(cycle_pos - 0.25) / 0.25   # 1 at new/0.5, 0 at 0.25
        term_rx = int(r * t)
        # Right semicircle + ellipse for terminator
        if cycle_pos < 0.25:
            # crescent: dark background, small lit sliver on right
            bg_fill = dark
            sliver_fill = lit
            sliver_d = (
                f"M {cx},{cy - r} "
                f"A {r},{r} 0 0,1 {cx},{cy + r} "        # right semicircle arc
                f"A {term_rx},{r} 0 0,0 {cx},{cy - r}"   # terminator ellipse back
            )
            return (
                f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{bg_fill}" stroke="{rim}" stroke-width="1.5"/>'
                f'<path d="{sliver_d}" fill="{sliver_fill}"/>'
                f'</svg>'
            )
        else:
            # gibbous waxing: lit background, dark sliver on left
            bg_fill = lit
            sliver_fill = dark
            sliver_d = (
                f"M {cx},{cy - r} "
                f"A {r},{r} 0 0,0 {cx},{cy + r} "        # left semicircle arc
                f"A {term_rx},{r} 0 0,1 {cx},{cy - r}"   # terminator ellipse
            )
            return (
                f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{bg_fill}" stroke="{rim}" stroke-width="1.5"/>'
                f'<path d="{sliver_d}" fill="{sliver_fill}"/>'
                f'</svg>'
            )
    else:
        # Waning: left side lit
        t = abs((cycle_pos - 0.5) - 0.25) / 0.25
        term_rx = int(r * t)
        if cycle_pos < 0.75:
            # gibbous waning: lit background, dark sliver on right
            bg_fill = lit
            sliver_fill = dark
            sliver_d = (
                f"M {cx},{cy - r} "
                f"A {r},{r} 0 0,1 {cx},{cy + r} "
                f"A {term_rx},{r} 0 0,0 {cx},{cy - r}"
            )
            return (
                f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{bg_fill}" stroke="{rim}" stroke-width="1.5"/>'
                f'<path d="{sliver_d}" fill="{sliver_fill}"/>'
                f'</svg>'
            )
        else:
            # crescent waning: dark background, lit sliver on left
            bg_fill = dark
            sliver_fill = lit
            sliver_d = (
                f"M {cx},{cy - r} "
                f"A {r},{r} 0 0,0 {cx},{cy + r} "
                f"A {term_rx},{r} 0 0,1 {cx},{cy - r}"
            )
            return (
                f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{bg_fill}" stroke="{rim}" stroke-width="1.5"/>'
                f'<path d="{sliver_d}" fill="{sliver_fill}"/>'
                f'</svg>'
            )


def rain_svg(size: int = 40) -> str:
    """Simple rain drop SVG icon."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M20 4 C20 4 8 18 8 24 a12 12 0 0 0 24 0 C32 18 20 4 20 4 Z" '
        f'fill="#4db8ff" opacity="0.9"/>'
        f'<line x1="13" y1="34" x2="10" y2="40" stroke="#4db8ff" stroke-width="2.5" stroke-linecap="round"/>'
        f'<line x1="20" y1="34" x2="17" y2="40" stroke="#4db8ff" stroke-width="2.5" stroke-linecap="round"/>'
        f'<line x1="27" y1="34" x2="24" y2="40" stroke="#4db8ff" stroke-width="2.5" stroke-linecap="round"/>'
        f'</svg>'
    )


# ─────────────────────────────────────────────
# Moon phase calculation
# ─────────────────────────────────────────────
def get_moon_phase() -> tuple:
    KNOWN_NEW_MOON = datetime(2025, 1, 29, 12, 35, tzinfo=timezone.utc)
    SYNODIC        = 29.53058867

    now_utc    = datetime.now(AST).astimezone(timezone.utc)
    elapsed    = (now_utc - KNOWN_NEW_MOON).total_seconds() / 86400
    cycle_pos  = (elapsed % SYNODIC) / SYNODIC
    illumination = int((1 - math.cos(2 * math.pi * cycle_pos)) / 2 * 100)

    phases = [
        (0.0625, "New Moon"),
        (0.1875, "Waxing Crescent"),
        (0.3125, "First Quarter"),
        (0.4375, "Waxing Gibbous"),
        (0.5625, "Full Moon"),
        (0.6875, "Waning Gibbous"),
        (0.8125, "Last Quarter"),
        (0.9375, "Waning Crescent"),
        (1.0001, "New Moon"),
    ]
    name = "New Moon"
    for threshold, n in phases:
        if cycle_pos < threshold:
            name = n
            break

    svg = moon_svg(cycle_pos, size=44)
    return svg, name, illumination, cycle_pos


# ─────────────────────────────────────────────
# Logo loader
# ─────────────────────────────────────────────
def load_logo() -> str:
    for candidate in [
        SCRIPT_DIR / "logo.jpg",
        SCRIPT_DIR / "logo.png",
        SCRIPT_DIR.parent / "logo.jpg",
        SCRIPT_DIR.parent / "logo.png",
    ]:
        if candidate.exists():
            print(f"  Logo loaded: {candidate}")
            return base64.b64encode(candidate.read_bytes()).decode("utf-8")
    print("  WARNING: No logo.jpg found", file=sys.stderr)
    return ""


# ─────────────────────────────────────────────
# Generic fetch
# ─────────────────────────────────────────────
def fetch_url(url: str, as_json: bool = False):
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RabirubiaWeather/1.0 (rabirubiaweather.com)",
                "Accept": "application/geo+json" if as_json else "text/plain",
            }
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if as_json else raw
    except Exception as e:
        print(f"  WARNING: Could not fetch {url}: {e}", file=sys.stderr)
        return None if as_json else ""


# ─────────────────────────────────────────────
# Rain probability
# ─────────────────────────────────────────────
def fetch_rain_probability() -> str:
    data = fetch_url(NWS_FORECAST_URL, as_json=True)
    if not data:
        return "N/A"
    try:
        today_date = datetime.now(AST).date()
        for period in data["properties"]["periods"]:
            start_str = period.get("startTime", "")
            try:
                period_date = datetime.strptime(start_str[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if period_date == today_date and period.get("isDaytime", True):
                pop = period.get("probabilityOfPrecipitation", {})
                val = pop.get("value") if isinstance(pop, dict) else pop
                if val is not None:
                    return str(int(val)) + "%"
        # Fallback — first period
        if data["properties"]["periods"]:
            pop = data["properties"]["periods"][0].get("probabilityOfPrecipitation", {})
            val = pop.get("value") if isinstance(pop, dict) else pop
            if val is not None:
                return str(int(val)) + "%"
    except Exception as e:
        print(f"  WARNING: Rain parse error: {e}", file=sys.stderr)
    return "N/A"


# ─────────────────────────────────────────────
# Synopsis
# ─────────────────────────────────────────────
def fetch_synopsis() -> str:
    text = fetch_url(NWS_COMBINED_URL) or fetch_url(NWS_SYNOPSIS_URL)
    if not text:
        return ""
    for pattern in [
        r"\.SYNOPSIS\.\.\.(.+?)(?=\n\.[A-Z]|\$\$|\Z)",
        r"SYNOPSIS[^\n]*\n(.+?)(?=\n[A-Z]{3}[0-9]|\$\$|\nAMZ|\Z)",
    ]:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1).strip())[:420]
    return ""


# ─────────────────────────────────────────────
# Zone parser
# ─────────────────────────────────────────────
def parse_zone(text: str) -> dict:
    data = {"wind": "Check NWS", "gusts": "", "seas": "Check NWS",
            "wave_detail": "", "advisory": "", "precip": ""}
    if not text:
        return data

    adv = re.search(
        r"(SMALL CRAFT ADVISORY[^\n]*|GALE WARNING[^\n]*|STORM WARNING[^\n]*|HURRICANE FORCE[^\n]*)",
        text, re.IGNORECASE
    )
    if adv:
        data["advisory"] = adv.group(1).strip().title()

    today = re.search(
        r"\.TODAY\.\.\.(.*?)(?=\.TONIGHT|\.WEDNESDAY NIGHT|\.THURSDAY NIGHT|\.FRIDAY|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if not today:
        today = re.search(r"TODAY\s*\n(.*?)(?=TONIGHT|\Z)", text, re.DOTALL | re.IGNORECASE)
    block = re.sub(r"\s+", " ", today.group(1) if today else text[:1000])

    wm = re.search(
        r"((?:North|South|East|West|NE|NW|SE|SW|[NSEW]+)"
        r"(?:\s+to\s+(?:North|South|East|West|NE|NW|SE|SW|[NSEW]+))?"
        r"\s+winds?\s+\d+(?:\s+to\s+\d+)?\s+knots?)",
        block, re.IGNORECASE
    )
    if wm:
        w = re.sub(r"\s*winds?\s*", " ", wm.group(1).strip(), flags=re.IGNORECASE).strip()
        data["wind"] = re.sub(r"\s+knots?", " kt", w, flags=re.IGNORECASE)

    gm = re.search(r"gusts?\s+(?:up\s+to\s+)?(\d+)\s+knots?", block, re.IGNORECASE)
    if gm:
        data["gusts"] = "Gusts to " + gm.group(1) + " kt"

    sm = re.search(r"[Ss]eas?\s+(\d+\s+to\s+\d+|\d+)\s+feet?", block, re.IGNORECASE)
    if sm:
        data["seas"] = sm.group(1) + " ft"

    wave = re.search(r"[Ww]ave\s+[Dd]etail:?\s*([^.;\n]+)", block)
    if wave:
        dirs = {"north": "N", "south": "S", "east": "E", "west": "W",
                "northeast": "NE", "northwest": "NW", "southeast": "SE", "southwest": "SW"}
        parts = re.split(r"\s+and\s+", wave.group(1).strip(), flags=re.IGNORECASE)
        out = []
        for p in parts:
            m = re.match(r"(\w+)\s+(\d+)\s+feet?\s+at\s+(\d+)\s+seconds?", p.strip(), re.IGNORECASE)
            if m:
                d = dirs.get(m.group(1).lower(), m.group(1).upper()[:2])
                out.append(d + " " + m.group(2) + "ft@" + m.group(3) + "s")
            elif p.strip():
                out.append(p.strip())
        data["wave_detail"] = " + ".join(out)

    for kw in ["thunderstorm", "showers", "rain", "sunny", "partly cloudy", "cloudy", "clear"]:
        if kw.lower() in block.lower():
            m = re.search(r"([^.]*" + re.escape(kw) + r"[^.]*\.)", block, re.IGNORECASE)
            if m:
                data["precip"] = m.group(1).strip()[:90]
            break

    return data


# ─────────────────────────────────────────────
# Advisories
# ─────────────────────────────────────────────
def get_advisories(zones: dict) -> list:
    found = set()
    for z in zones.values():
        adv = z.get("advisory", "")
        if adv:
            if "small craft" in adv.lower():   found.add("Small Craft Advisory")
            elif "gale" in adv.lower():         found.add("Gale Warning")
            elif "storm" in adv.lower():        found.add("Storm Warning")
            elif "hurricane" in adv.lower():    found.add("Hurricane Force Wind Warning")
            else:                               found.add(adv)
    return sorted(found) if found else ["No Active Advisories"]


# ─────────────────────────────────────────────
# HTML builder
# ─────────────────────────────────────────────
def build_html(zones, synopsis, date_str, time_str,
               rain_pct, moon_svg_str, moon_name, moon_illum,
               logo_b64) -> str:

    atl = zones["atlantic"]
    npr = zones["north_pr"]
    epr = zones["east_pr"]
    car = zones["caribbean"]

    advisories  = get_advisories(zones)
    adv_text    = " &nbsp;|&nbsp; ".join(advisories)
    has_warning = any("advisory" in a.lower() or "warning" in a.lower() for a in advisories)
    alert_bg    = "#8b0000, #cc1616, #8b0000" if has_warning else "#0a4a00, #0c7a00, #0a4a00"

    if not synopsis:
        synopsis = "Synopsis unavailable — visit weather.gov/sju for current marine forecast."
    tags_html = "".join('<span class="tag">' + a + '</span>' for a in advisories)

    logo_img = ('<img class="logo" src="data:image/jpeg;base64,' + logo_b64 + '"/>'
                if logo_b64 else '<div style="width:84px;height:84px"></div>')

    def zone_td(z, cls, name):
        return (
            '<td class="' + cls + '">'
            '<div class="zone-name">' + name + '</div>'
            '<div class="stat"><div class="stat-lbl">WIND</div>'
            '<div class="stat-val">' + z["wind"] + '</div>'
            '<div class="stat-note">' + z["gusts"] + '</div></div>'
            '<div class="stat"><div class="stat-lbl">SEAS</div>'
            '<div class="stat-val">' + z["seas"] + '</div>'
            '<div class="stat-note">' + z["wave_detail"] + '</div></div>'
            '</td>'
        )

    fishing = (
        "Rough &mdash; offshore not recommended"
        if any(x in atl["seas"] for x in ["8 ", "9 ", "10", "11", "12", "13", "14", "15"])
        else "Moderate &mdash; check conditions"
    )
    precip = atl.get("precip") or "&mdash;"

    return """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{width:1080px;height:1080px;overflow:hidden;background:#060e1f;font-family:Arial,Helvetica,sans-serif}
.card{width:1080px;height:1080px;background:linear-gradient(145deg,#060e1f 0%,#0a1f3d 45%,#071428 100%);display:table}
.ci{display:table-cell;vertical-align:top}

/* HEADER */
.hdr{background:linear-gradient(135deg,#0d2050,#142e6e);padding:15px 28px 13px;border-bottom:3px solid #cc1818}
.hdr table{width:100%;border-collapse:collapse}
.hdr td{vertical-align:middle;padding:0}
.logo{width:82px;height:82px;object-fit:contain;display:block}
.brand{font-family:'Arial Black',Impact,sans-serif;font-size:33px;font-weight:900;color:#ffffff;letter-spacing:2px;text-transform:uppercase;line-height:1}
.sub{font-size:12px;color:#aaddff;letter-spacing:3px;text-transform:uppercase;margin-top:4px}
.datebig{font-family:'Arial Black',Impact,sans-serif;font-size:42px;font-weight:900;color:#dd1c1c;line-height:1;text-align:right}
.datetime{font-family:'Arial Black',Impact,sans-serif;font-size:15px;font-weight:900;color:#ffffff;letter-spacing:2px;text-align:right;margin-top:4px}

/* INFO BAR */
.infobar{background:rgba(0,0,0,0.4);border-bottom:1px solid rgba(255,255,255,0.12);padding:9px 28px;text-align:center}
.pill{display:inline-block;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.18);border-radius:40px;padding:6px 24px 6px 10px;margin:0 12px;vertical-align:middle}
.pill-icon{display:inline-block;vertical-align:middle;margin-right:10px}
.pill-text{display:inline-block;vertical-align:middle;text-align:left}
.pill-label{font-size:9px;color:#88bbdd;text-transform:uppercase;letter-spacing:1.5px;display:block;line-height:1;margin-bottom:3px}
.pill-value{font-family:'Arial Black',Impact,sans-serif;font-size:17px;font-weight:900;color:#ffffff;letter-spacing:1px;display:block;line-height:1}
.pill-sub{font-size:10px;color:#aaccee;margin-top:2px;display:block}

/* ADVISORY */
.alert{background:linear-gradient(90deg,""" + alert_bg + """);padding:9px 28px;color:#ffffff;font-family:'Arial Narrow',Arial,sans-serif;font-size:14px;font-weight:700;letter-spacing:2px;text-transform:uppercase;text-align:center}

/* ZONES */
.grid{width:100%;padding:10px 14px 6px}
.gt{width:100%;border-collapse:separate;border-spacing:7px}
.gt td{width:25%;vertical-align:top;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.15);border-radius:10px;padding:12px}
.z1{border-top:3px solid #1e88e5!important}
.z2{border-top:3px solid #0288d1!important}
.z3{border-top:3px solid #00acc1!important}
.z4{border-top:3px solid #00897b!important}
.zone-name{font-family:'Arial Narrow',Arial,sans-serif;font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#aaddff;margin-bottom:9px;line-height:1.4;border-bottom:2px solid rgba(255,255,255,.15);padding-bottom:6px}
.stat{margin-bottom:8px}
.stat-lbl{font-size:9px;color:#88bbdd;text-transform:uppercase;letter-spacing:1.5px;line-height:1;margin-bottom:2px}
.stat-val{font-family:'Arial Black',Impact,sans-serif;font-size:19px;font-weight:900;color:#ffffff;line-height:1.1}
.stat-note{font-size:11px;color:#ffffff;line-height:1.3}

/* BOTTOM */
.bt{width:100%;border-collapse:separate;border-spacing:7px}
.bt td{vertical-align:top;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:10px;padding:12px}
.stitle{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#aaddff;margin-bottom:7px}
.bval{font-family:'Arial Black',Impact,sans-serif;font-size:17px;font-weight:900;color:#ffffff;line-height:1.1;margin-bottom:2px}
.bnote{font-size:11px;color:#ffffff;line-height:1.4}
.blbl{font-size:9px;color:#88bbdd;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:2px}
.stext{font-size:12px;color:#ffffff;line-height:1.6}
.tags{margin-top:8px}
.tag{display:inline-block;background:rgba(160,20,20,.3);border:1px solid rgba(220,60,60,.6);border-radius:20px;padding:3px 10px;font-size:10px;color:#ffaaaa;letter-spacing:.8px;text-transform:uppercase;font-weight:700;margin:3px 3px 0 0}

/* FOOTER */
.ftr{background:rgba(0,0,0,.4);border-top:1px solid rgba(255,255,255,.1);padding:9px 28px}
.ftr table{width:100%;border-collapse:collapse}
.fsrc{font-size:11px;color:#6699bb}
.furl{font-family:'Arial Narrow',Arial,sans-serif;font-size:16px;font-weight:700;color:#4db8ff;letter-spacing:1px;text-align:right}
</style></head>
<body>
<div class="card"><div class="ci">

<!-- HEADER -->
<div class="hdr"><table><tr>
  <td style="width:94px">""" + logo_img + """</td>
  <td style="padding-left:14px">
    <div class="brand">Rabirubia Weather</div>
    <div class="sub">Marine Forecast &mdash; PR &amp; USVI</div>
  </td>
  <td style="width:230px">
    <div class="datebig">""" + date_str + """</div>
    <div class="datetime">""" + time_str + """ AST</div>
  </td>
</tr></table></div>

<!-- INFO BAR: Moon + Rain -->
<div class="infobar">

  <div class="pill">
    <span class="pill-icon">""" + moon_svg_str + """</span>
    <span class="pill-text">
      <span class="pill-label">Moon Phase</span>
      <span class="pill-value">""" + moon_name + """</span>
      <span class="pill-sub">""" + str(moon_illum) + """% illuminated</span>
    </span>
  </div>

  <div class="pill">
    <span class="pill-icon">""" + rain_svg(40) + """</span>
    <span class="pill-text">
      <span class="pill-label">Rain Probability Today</span>
      <span class="pill-value">""" + rain_pct + """</span>
      <span class="pill-sub">San Juan area</span>
    </span>
  </div>

</div>

<!-- ADVISORY -->
<div class="alert">""" + adv_text + """</div>

<!-- ZONE GRID -->
<div class="grid"><table class="gt"><tr>
  """ + zone_td(atl, "z1", "Atlantic Offshore<br>(10NM &ndash; 19.5&deg;N)") + """
  """ + zone_td(npr, "z2", "Northern PR Coast<br>(out 10 NM)") + """
  """ + zone_td(epr, "z3", "East PR / Vieques<br>Culebra &amp; St. John") + """
  """ + zone_td(car, "z4", "Caribbean Waters<br>PR + St. Croix") + """
</tr></table></div>

<!-- BOTTOM ROW -->
<div style="padding:0 14px 6px"><table class="bt"><tr>

  <td style="width:25%">
    <div class="stitle">Swell Summary</div>
    <div class="stat">
      <div class="blbl">Atlantic Swell</div>
      <div class="bval">""" + atl["seas"] + """</div>
      <div class="bnote">""" + (atl["wave_detail"] or "&mdash;") + """</div>
    </div>
    <div class="stat">
      <div class="blbl">Caribbean Seas</div>
      <div class="bval">""" + car["seas"] + """</div>
      <div class="bnote">""" + (car["wave_detail"] or "&mdash;") + """</div>
    </div>
  </td>

  <td style="width:25%">
    <div class="stitle">Conditions</div>
    <div class="stat">
      <div class="blbl">Precip</div>
      <div class="bnote">""" + precip + """</div>
    </div>
    <div class="stat">
      <div class="blbl">Fishing</div>
      <div class="bnote">""" + fishing + """</div>
    </div>
  </td>

  <td style="width:50%">
    <div class="stitle">Synopsis</div>
    <div class="stext">""" + synopsis + """</div>
    <div class="tags">""" + tags_html + """</div>
  </td>

</tr></table></div>

<!-- FOOTER -->
<div class="ftr"><table><tr>
  <td class="fsrc">Source: NWS San Juan &middot; NOAA</td>
  <td class="furl">www.rabirubiaweather.com</td>
</tr></table></div>

</div></div>
</body></html>"""


# ─────────────────────────────────────────────
# Render HTML → JPG
# ─────────────────────────────────────────────
def render_jpg(html: str, output_path: Path) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        tmp_html = f.name
    raw_jpg = tmp_html.replace(".html", "_raw.jpg")
    try:
        subprocess.run(
            ["wkhtmltoimage", "--width", "1080", "--height", "1080",
             "--quality", "95", "--log-level", "none", "--format", "jpg",
             tmp_html, raw_jpg],
            capture_output=True, text=True,
        )
        if not Path(raw_jpg).exists() or Path(raw_jpg).stat().st_size < 5000:
            print("ERROR: wkhtmltoimage did not produce a valid image.", file=sys.stderr)
            return False
        try:
            from PIL import Image
            img     = Image.open(raw_jpg)
            cropped = img.crop((0, 0, 1080, min(790, img.size[1])))
            cropped.resize((1080, 1080), Image.LANCZOS).save(str(output_path), "JPEG", quality=95)
        except ImportError:
            shutil.move(raw_jpg, str(output_path))
        return True
    finally:
        for p in [tmp_html, raw_jpg]:
            try:
                if Path(p).exists():
                    os.unlink(p)
            except Exception:
                pass


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    now      = datetime.now(AST)
    date_str = now.strftime("%b %d").upper()
    time_str = now.strftime("%-I:%M %p")

    print("Rabirubia Weather Card — " + date_str + " " + time_str + " AST")
    print("Output: " + str(FIXED_OUTPUT))

    print("Loading logo...")
    logo_b64 = load_logo()

    print("Calculating moon phase...")
    moon_svg_str, moon_name, moon_illum, cycle_pos = get_moon_phase()
    print(f"  {moon_name} ({moon_illum}% illuminated, cycle={cycle_pos:.3f})")

    print("Fetching rain probability...")
    rain_pct = fetch_rain_probability()
    print(f"  Rain probability: {rain_pct}")

    print("Fetching synopsis...")
    synopsis = fetch_synopsis()
    print("  Synopsis: " + (synopsis[:80] + "..." if synopsis else "NOT FOUND"))

    print("Fetching zone forecasts...")
    raw   = {name: fetch_url(url) for name, url in NWS_ZONES.items()}

    print("Parsing forecast data...")
    zones = {name: parse_zone(text) for name, text in raw.items()}
    for name, z in zones.items():
        print("  " + name + ": wind=" + z["wind"] + " | seas=" + z["seas"])

    print("Rendering image...")
    html    = build_html(zones, synopsis, date_str, time_str,
                         rain_pct, moon_svg_str, moon_name, moon_illum, logo_b64)
    success = render_jpg(html, FIXED_OUTPUT)

    if success:
        print("Done! -> " + str(FIXED_OUTPUT))
    else:
        print("FAILED to render image.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
