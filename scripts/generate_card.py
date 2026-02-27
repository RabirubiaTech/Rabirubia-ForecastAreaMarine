#!/usr/bin/env python3
"""
Rabirubia Weather Card Generator
Fetches NWS San Juan marine forecasts and generates a daily Instagram-ready JPG.
Output is always saved as: output/marine_forecast.jpg  (fixed name for embedding)
"""

import os
import re
import sys
import base64
import subprocess
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import urllib.request

# ─────────────────────────────────────────────
# NWS zone URLs — direct NOAA text, no API key
# ─────────────────────────────────────────────
NWS_ZONES = {
    "atlantic":  "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz711.txt",
    "north_pr":  "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz712.txt",
    "east_pr":   "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz726.txt",
    "caribbean": "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz733.txt",
}

SCRIPT_DIR  = Path(__file__).parent
OUTPUT_DIR  = Path(os.environ.get("OUTPUT_DIR", SCRIPT_DIR.parent / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FIXED_OUTPUT = OUTPUT_DIR / "marine_forecast.jpg"


# ─────────────────────────────────────────────
# Load logo from logo.jpg in the scripts/ folder
# ─────────────────────────────────────────────
def load_logo() -> str:
    """Return base64-encoded logo string, or empty string if not found."""
    # Try logo.jpg sitting next to this script
    for candidate in [
        SCRIPT_DIR / "logo.jpg",
        SCRIPT_DIR / "logo.png",
        SCRIPT_DIR.parent / "logo.jpg",
        SCRIPT_DIR.parent / "logo.png",
    ]:
        if candidate.exists():
            print(f"  Logo loaded from: {candidate}")
            raw = candidate.read_bytes()
            return base64.b64encode(raw).decode("utf-8")

    print("  WARNING: No logo.jpg found — logo will be blank", file=sys.stderr)
    return ""


# ─────────────────────────────────────────────
# Fetch NWS text
# ─────────────────────────────────────────────
def fetch_nws(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RabirubiaWeather/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  WARNING: Could not fetch {url}: {e}", file=sys.stderr)
        return ""


# ─────────────────────────────────────────────
# Parse a single zone forecast block
# ─────────────────────────────────────────────
def parse_zone(text: str) -> dict:
    data = {
        "wind": "Check NWS",
        "gusts": "",
        "seas": "Check NWS",
        "wave_detail": "",
        "advisory": "",
        "synopsis": "",
        "precip": "",
    }
    if not text:
        return data

    # Advisory
    adv = re.search(
        r"(SMALL CRAFT ADVISORY[^\n]*|GALE WARNING[^\n]*|STORM WARNING[^\n]*|HURRICANE FORCE[^\n]*)",
        text, re.IGNORECASE
    )
    if adv:
        data["advisory"] = adv.group(1).strip().title()

    # Synopsis block
    syn_match = re.search(
        r"SYNOPSIS[^\n]*\n(.*?)(?=\n[A-Z]{3}\d{6}|\nAMZ|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if syn_match:
        syn = re.sub(r"\s+", " ", syn_match.group(1).strip())
        data["synopsis"] = syn[:400]

    # TODAY section
    today = re.search(
        r"\.TODAY\.\.\.(.*?)(?=\.TONIGHT|\.WEDNESDAY NIGHT|\.THURSDAY NIGHT|\.FRIDAY|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if not today:
        today = re.search(r"TODAY\s*\n(.*?)(?=TONIGHT|\Z)", text, re.DOTALL | re.IGNORECASE)
    block = re.sub(r"\s+", " ", today.group(1) if today else text[:1000])

    # Wind
    wind_match = re.search(
        r"((?:North|South|East|West|NE|NW|SE|SW|[NSEW]+)"
        r"(?:\s+to\s+(?:North|South|East|West|NE|NW|SE|SW|[NSEW]+))?"
        r"\s+winds?\s+\d+(?:\s+to\s+\d+)?\s+knots?)",
        block, re.IGNORECASE
    )
    if wind_match:
        w = wind_match.group(1).strip()
        w = re.sub(r"\s*winds?\s*", " ", w, flags=re.IGNORECASE).strip()
        w = re.sub(r"\s+knots?", " kt", w, flags=re.IGNORECASE)
        data["wind"] = w

    # Gusts
    gust = re.search(r"gusts?\s+(?:up\s+to\s+)?(\d+)\s+knots?", block, re.IGNORECASE)
    if gust:
        data["gusts"] = "Gusts to " + gust.group(1) + " kt"

    # Seas
    seas = re.search(r"[Ss]eas?\s+(\d+\s+to\s+\d+|\d+)\s+feet?", block, re.IGNORECASE)
    if seas:
        data["seas"] = seas.group(1) + " ft"

    # Wave detail
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

    # Precip
    for kw in ["thunderstorm", "showers", "rain", "sunny", "partly cloudy", "cloudy", "clear"]:
        if kw.lower() in block.lower():
            m = re.search(r"([^.]*" + re.escape(kw) + r"[^.]*\.)", block, re.IGNORECASE)
            if m:
                data["precip"] = m.group(1).strip()[:90]
            break

    return data


# ─────────────────────────────────────────────
# Build advisory list
# ─────────────────────────────────────────────
def get_advisories(zones: dict) -> list:
    found = set()
    for z in zones.values():
        adv = z.get("advisory", "")
        if adv:
            if "small craft" in adv.lower():
                found.add("Small Craft Advisory")
            elif "gale" in adv.lower():
                found.add("Gale Warning")
            elif "storm" in adv.lower():
                found.add("Storm Warning")
            elif "hurricane" in adv.lower():
                found.add("Hurricane Force Wind Warning")
            else:
                found.add(adv)
    syn = " ".join(z.get("synopsis", "") for z in zones.values()).lower()
    if "rip current" in syn:
        found.add("Rip Currents")
    if "breaking wave" in syn or "hazardous surf" in syn:
        found.add("Breaking Waves")
    return sorted(found) if found else ["No Active Advisories"]


# ─────────────────────────────────────────────
# Build HTML card
# ─────────────────────────────────────────────
def build_html(zones: dict, date_str: str, logo_b64: str) -> str:
    atl = zones["atlantic"]
    npr = zones["north_pr"]
    epr = zones["east_pr"]
    car = zones["caribbean"]

    advisories  = get_advisories(zones)
    adv_text    = " | ".join(advisories)
    has_warning = any("advisory" in a.lower() or "warning" in a.lower() for a in advisories)
    alert_bg    = "#8b0000, #cc1616, #8b0000" if has_warning else "#0a4a00, #0c7a00, #0a4a00"

    synopsis = (atl.get("synopsis") or npr.get("synopsis") or
                epr.get("synopsis") or "Forecast data unavailable. Check NWS San Juan.")
    synopsis = synopsis[:390]

    tags_html = "".join('<span class="tag">' + a + '</span>' for a in advisories)

    # Logo img tag — use base64 data URI if available, else hide
    if logo_b64:
        logo_img = '<img class="logo" src="data:image/jpeg;base64,' + logo_b64 + '"/>'
    else:
        logo_img = '<div style="width:88px;height:88px"></div>'

    def zone_td(z, cls, name):
        return (
            '<td class="' + cls + '">'
            '<div class="zone-name">' + name + '</div>'
            '<div class="stat">'
            '<div class="stat-lbl">WIND</div>'
            '<div class="stat-val">' + z["wind"] + '</div>'
            '<div class="stat-note">' + z["gusts"] + '</div>'
            '</div>'
            '<div class="stat">'
            '<div class="stat-lbl">SEAS</div>'
            '<div class="stat-val">' + z["seas"] + '</div>'
            '<div class="stat-note">' + z["wave_detail"] + '</div>'
            '</div>'
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
.hdr{background:linear-gradient(135deg,#0d2050,#142e6e);padding:18px 28px;border-bottom:4px solid #cc1818}
.hdr table{width:100%;border-collapse:collapse}
.hdr td{vertical-align:middle;padding:0}
.logo{width:88px;height:88px;object-fit:contain;display:block}
.brand{font-family:'Arial Black',Impact,sans-serif;font-size:36px;font-weight:900;color:#fff;letter-spacing:2px;text-transform:uppercase;line-height:1}
.sub{font-size:13px;color:#7ec8e3;letter-spacing:3px;text-transform:uppercase;margin-top:5px}
.datebig{font-family:'Arial Black',Impact,sans-serif;font-size:52px;font-weight:900;color:#dd1c1c;line-height:1;text-align:right}
.datesml{font-size:12px;color:#7a9bb5;letter-spacing:2px;text-transform:uppercase;text-align:right;margin-top:3px}
.alert{background:linear-gradient(90deg,""" + alert_bg + """);padding:10px 28px;color:#fff;font-family:'Arial Narrow',Arial,sans-serif;font-size:15px;font-weight:700;letter-spacing:2px;text-transform:uppercase}
.grid{width:100%;padding:12px 16px 8px;display:block}
.gt{width:100%;border-collapse:separate;border-spacing:8px}
.gt td{width:25%;vertical-align:top;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:10px;padding:14px}
.z1{border-top:3px solid #1565c0!important}
.z2{border-top:3px solid #0277bd!important}
.z3{border-top:3px solid #00838f!important}
.z4{border-top:3px solid #00695c!important}
.zone-name{font-family:'Arial Narrow',Arial,sans-serif;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#7ec8e3;margin-bottom:10px;line-height:1.4;border-bottom:2px solid rgba(255,255,255,.1);padding-bottom:7px}
.stat{margin-bottom:9px}
.stat-lbl{font-size:9px;color:#4a7a9a;text-transform:uppercase;letter-spacing:1.5px;line-height:1}
.stat-val{font-family:'Arial Black',Impact,sans-serif;font-size:20px;font-weight:900;color:#e0f0ff;line-height:1.1}
.stat-note{font-size:11px;color:#5ba8cc;line-height:1.3}
.bt{width:100%;border-collapse:separate;border-spacing:8px}
.bt td{vertical-align:top;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:14px}
.stitle{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#7ec8e3;margin-bottom:8px}
.stext{font-size:12.5px;color:#9ab8d0;line-height:1.6}
.tags{margin-top:10px}
.tag{display:inline-block;background:rgba(160,20,20,.25);border:1px solid rgba(200,40,40,.5);border-radius:20px;padding:4px 11px;font-size:10.5px;color:#ff8888;letter-spacing:.8px;text-transform:uppercase;font-weight:700;margin:3px 3px 0 0}
.ftr{background:rgba(0,0,0,.4);border-top:1px solid rgba(255,255,255,.07);padding:10px 28px}
.ftr table{width:100%;border-collapse:collapse}
.fsrc{font-size:11px;color:#3a5a7a}
.furl{font-family:'Arial Narrow',Arial,sans-serif;font-size:17px;font-weight:700;color:#1e88e5;letter-spacing:1px;text-align:right}
</style></head>
<body>
<div class="card"><div class="ci">

<div class="hdr"><table><tr>
  <td style="width:100px">""" + logo_img + """</td>
  <td style="padding-left:14px">
    <div class="brand">Rabirubia Weather</div>
    <div class="sub">Marine Forecast &mdash; PR &amp; USVI</div>
  </td>
  <td style="width:220px">
    <div class="datebig">""" + date_str + """</div>
    <div class="datesml">AST</div>
  </td>
</tr></table></div>

<div class="alert">""" + adv_text + """</div>

<div class="grid"><table class="gt"><tr>
  """ + zone_td(atl, "z1", "Atlantic Offshore<br>(10NM &ndash; 19.5&deg;N)") + """
  """ + zone_td(npr, "z2", "Northern PR Coast<br>(out 10 NM)") + """
  """ + zone_td(epr, "z3", "East PR / Vieques<br>Culebra &amp; St. John") + """
  """ + zone_td(car, "z4", "Caribbean Waters<br>PR + St. Croix") + """
</tr></table></div>

<div style="padding:0 16px 8px"><table class="bt"><tr>
  <td style="width:25%">
    <div class="stitle">Swell Summary</div>
    <div class="stat">
      <div class="stat-lbl">Atlantic Swell</div>
      <div class="stat-val" style="font-size:18px">""" + atl["seas"] + """</div>
      <div class="stat-note">""" + (atl["wave_detail"] or "&mdash;") + """</div>
    </div>
    <div class="stat">
      <div class="stat-lbl">Caribbean Seas</div>
      <div class="stat-val" style="font-size:18px">""" + car["seas"] + """</div>
      <div class="stat-note">""" + (car["wave_detail"] or "&mdash;") + """</div>
    </div>
  </td>
  <td style="width:25%">
    <div class="stitle">Conditions</div>
    <div class="stat">
      <div class="stat-lbl">Precip</div>
      <div class="stat-note" style="font-size:12px;color:#9ab8d0">""" + precip + """</div>
    </div>
    <div class="stat">
      <div class="stat-lbl">Fishing</div>
      <div class="stat-note" style="font-size:12px;color:#9ab8d0">""" + fishing + """</div>
    </div>
  </td>
  <td style="width:50%">
    <div class="stitle">Synopsis</div>
    <div class="stext">""" + synopsis + """</div>
    <div class="tags">""" + tags_html + """</div>
  </td>
</tr></table></div>

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
            # Do NOT use check=True — wkhtmltoimage returns non-zero
            # for font/network warnings even when image renders fine
        )

        if not Path(raw_jpg).exists() or Path(raw_jpg).stat().st_size < 5000:
            print("ERROR: wkhtmltoimage did not produce a valid image.", file=sys.stderr)
            return False

        try:
            from PIL import Image
            img = Image.open(raw_jpg)
            cropped = img.crop((0, 0, 1080, min(730, img.size[1])))
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
    now      = datetime.now()
    date_str = now.strftime("%b %d").upper()

    print("Rabirubia Weather Card Generator — " + date_str)
    print("Output: " + str(FIXED_OUTPUT))

    print("Loading logo...")
    logo_b64 = load_logo()

    print("Fetching NWS forecasts...")
    raw = {name: fetch_nws(url) for name, url in NWS_ZONES.items()}

    print("Parsing forecast data...")
    zones = {name: parse_zone(text) for name, text in raw.items()}
    for name, z in zones.items():
        print("  " + name + ": wind=" + z["wind"] + " | seas=" + z["seas"])

    print("Rendering image...")
    html    = build_html(zones, date_str, logo_b64)
    success = render_jpg(html, FIXED_OUTPUT)

    if success:
        print("Done! -> " + str(FIXED_OUTPUT))
    else:
        print("FAILED to render image.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
