#!/usr/bin/env python3
"""
Rabirubia Weather Card Generator
Fetches NWS San Juan marine forecasts and generates a daily Instagram-ready JPG.
"""

import os
import re
import sys
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.error

# ─────────────────────────────────────────────
# NWS zone URLs (direct NOAA text files - no API key needed)
# ─────────────────────────────────────────────
NWS_ZONES = {
    "synopsis": "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz711.txt",
    "atlantic":  "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz711.txt",
    "north_pr":  "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz712.txt",
    "east_pr":   "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz726.txt",
    "caribbean": "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/am/amz733.txt",
}

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", SCRIPT_DIR.parent / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Fetch NWS text
# ─────────────────────────────────────────────
def fetch_nws(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RabirubiaWeather/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  WARNING: Could not fetch {url}: {e}", file=sys.stderr)
        return ""


# ─────────────────────────────────────────────
# Parse a single zone block
# ─────────────────────────────────────────────
def parse_zone(text: str) -> dict:
    """Extract TODAY wind, seas, wave detail, advisory, and synopsis from NWS text."""
    data = {
        "wind": "N/A",
        "gusts": "",
        "seas": "N/A",
        "wave_detail": "",
        "advisory": "",
        "synopsis": "",
        "precip": "",
    }

    if not text:
        return data

    # Advisory
    adv = re.search(r"(SMALL CRAFT ADVISORY[^\n]*|GALE WARNING[^\n]*|STORM WARNING[^\n]*|HURRICANE FORCE[^\n]*)", text, re.IGNORECASE)
    if adv:
        data["advisory"] = adv.group(1).strip().title()

    # Synopsis block
    syn_match = re.search(r"SYNOPSIS[^\n]*\n(.*?)(?=\n[A-Z]{3}\d{6}|\nAMZ|\Z)", text, re.DOTALL | re.IGNORECASE)
    if syn_match:
        syn = syn_match.group(1).strip()
        syn = re.sub(r"\s+", " ", syn)
        data["synopsis"] = syn[:400]

    # TODAY section
    today = re.search(r"\.TODAY\.\.\.(.*?)(?=\.TONIGHT|\Z)", text, re.DOTALL | re.IGNORECASE)
    if not today:
        today = re.search(r"TODAY\s*\n(.*?)(?=TONIGHT|\Z)", text, re.DOTALL | re.IGNORECASE)

    block = today.group(1) if today else text[:800]
    block = re.sub(r"\s+", " ", block)

    # Wind
    wind_match = re.search(
        r"((?:North|South|East|West|NE|NW|SE|SW|[NSEW]+(?:\s+to\s+[NSEW]+)?)\s+winds?\s+[\d]+(?:\s+to\s+[\d]+)?\s+knots?)",
        block, re.IGNORECASE
    )
    if wind_match:
        data["wind"] = wind_match.group(1).strip()
        # Simplify direction
        data["wind"] = re.sub(r"winds?\s+", "", data["wind"], flags=re.IGNORECASE).strip()
        data["wind"] = re.sub(r"\s+knots?", " kt", data["wind"], flags=re.IGNORECASE)

    # Gusts
    gust_match = re.search(r"gusts?\s+(?:up\s+to\s+)?(\d+)\s+knots?", block, re.IGNORECASE)
    if gust_match:
        data["gusts"] = f"Gusts to {gust_match.group(1)} kt"

    # Seas
    seas_match = re.search(r"[Ss]eas?\s+([\d]+\s+to\s+[\d]+|[\d]+)\s+feet?", block, re.IGNORECASE)
    if seas_match:
        data["seas"] = seas_match.group(1) + " ft"

    # Wave detail
    wave_match = re.search(r"[Ww]ave\s+[Dd]etail:?\s*([^\.\n]+)", block)
    if wave_match:
        detail = wave_match.group(1).strip()
        # Shorten: "East 5 feet at 6 seconds and northwest 2 feet at 11 seconds"
        # → "E 5ft@6s + NW 2ft@11s"
        def shorten_wave(s):
            dirs = {"north":"N","south":"S","east":"E","west":"W",
                    "northeast":"NE","northwest":"NW","southeast":"SE","southwest":"SW"}
            parts = re.split(r"\s+and\s+", s, flags=re.IGNORECASE)
            out = []
            for p in parts:
                p = p.strip()
                m = re.match(r"(\w+)\s+(\d+)\s+feet?\s+at\s+(\d+)\s+seconds?", p, re.IGNORECASE)
                if m:
                    d = dirs.get(m.group(1).lower(), m.group(1).upper()[:2])
                    out.append(f"{d} {m.group(2)}ft@{m.group(3)}s")
                else:
                    out.append(p)
            return " + ".join(out)
        data["wave_detail"] = shorten_wave(detail)

    # Precip / sky
    precip_keywords = ["showers", "rain", "thunderstorm", "sunny", "partly cloudy", "cloudy", "clear"]
    for kw in precip_keywords:
        if kw.lower() in block.lower():
            # Extract the sentence containing the keyword
            m = re.search(r"([^.]*" + kw + r"[^.]*\.)", block, re.IGNORECASE)
            if m:
                data["precip"] = m.group(1).strip()[:80]
            break

    return data


# ─────────────────────────────────────────────
# Detect active advisories across all zones
# ─────────────────────────────────────────────
def get_active_advisories(zones: dict) -> list:
    advisories = set()
    hazards = set()
    for z in zones.values():
        if z.get("advisory"):
            advisories.add(z["advisory"])
    # Rip current check from synopsis
    syn = zones.get("atlantic", {}).get("synopsis", "")
    if "rip current" in syn.lower():
        hazards.add("⚠️ Rip Currents")
    if "breaking wave" in syn.lower() or "hazardous surf" in syn.lower():
        hazards.add("🚫 Breaking Waves")

    result = []
    for a in sorted(advisories):
        if "small craft" in a.lower():
            result.append("⛵ Small Craft Advisory")
        elif "gale" in a.lower():
            result.append("💨 Gale Warning")
        elif "storm" in a.lower():
            result.append("🌀 Storm Warning")
        else:
            result.append(a)
    result.extend(sorted(hazards))
    return result if result else ["✅ No Active Advisories"]


# ─────────────────────────────────────────────
# Build HTML card
# ─────────────────────────────────────────────
def build_html(zones: dict, date_str: str, logo_b64: str) -> str:
    atl = zones["atlantic"]
    npr = zones["north_pr"]
    epr = zones["east_pr"]
    car = zones["caribbean"]

    advisories = get_active_advisories(zones)
    advisory_text = " &nbsp;|&nbsp; ".join(advisories)

    has_sca = any("small craft" in a.lower() for a in advisories)
    alert_color = "#8b0000, #cc1616, #8b0000" if has_sca else "#0a5200, #0d8000, #0a5200"

    synopsis = atl.get("synopsis") or npr.get("synopsis") or "Forecast data unavailable."
    synopsis = synopsis[:380]

    tags_html = ""
    for a in advisories:
        tags_html += f'<span class="tag">{a}</span>\n'

    def zone_html(z, cls, icon, name):
        return f"""
        <td class="{cls}">
          <div class="zone-name">{icon} {name}</div>
          <div class="stat">
            <div class="stat-lbl">💨 WIND</div>
            <div class="stat-val">{z['wind']}</div>
            <div class="stat-note">{z['gusts']}</div>
          </div>
          <div class="stat">
            <div class="stat-lbl">🌊 SEAS</div>
            <div class="stat-val">{z['seas']}</div>
            <div class="stat-note">{z['wave_detail']}</div>
          </div>
        </td>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width: 1080px;
  height: 1080px;
  overflow: hidden;
  background: #060e1f;
  font-family: Arial, Helvetica, sans-serif;
}}
.card {{
  width: 1080px;
  height: 1080px;
  background: linear-gradient(145deg, #060e1f 0%, #0a1f3d 45%, #071428 100%);
  display: table;
}}
.card-inner {{ display: table-cell; vertical-align: top; }}

.header {{
  background: linear-gradient(135deg, #0d2050, #142e6e);
  padding: 18px 28px;
  border-bottom: 4px solid #cc1818;
}}
.header table {{ width: 100%; border-collapse: collapse; }}
.header td {{ vertical-align: middle; padding: 0; }}
.logo {{ width: 88px; height: 88px; object-fit: contain; display: block; }}
.brand {{
  font-family: 'Arial Black', Impact, sans-serif;
  font-size: 36px; font-weight: 900; color: #ffffff;
  letter-spacing: 2px; text-transform: uppercase; line-height: 1;
}}
.sub {{ font-size: 13px; color: #7ec8e3; letter-spacing: 3px; text-transform: uppercase; margin-top: 5px; }}
.date-big {{
  font-family: 'Arial Black', Impact, sans-serif;
  font-size: 52px; font-weight: 900; color: #dd1c1c; line-height: 1; text-align: right;
}}
.date-small {{ font-size: 12px; color: #7a9bb5; letter-spacing: 2px; text-transform: uppercase; text-align: right; margin-top: 3px; }}

.alert {{
  background: linear-gradient(90deg, {alert_color});
  padding: 10px 28px; color: #fff;
  font-family: 'Arial Narrow', Arial, sans-serif;
  font-size: 15px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase;
}}

.grid {{ width: 100%; padding: 12px 16px 8px; display: block; }}
.grid-table {{ width: 100%; border-collapse: separate; border-spacing: 8px; }}
.grid-table td {{
  width: 25%; vertical-align: top;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px; padding: 14px;
}}
.z1 {{ border-top: 3px solid #1565c0 !important; }}
.z2 {{ border-top: 3px solid #0277bd !important; }}
.z3 {{ border-top: 3px solid #00838f !important; }}
.z4 {{ border-top: 3px solid #00695c !important; }}

.zone-name {{
  font-family: 'Arial Narrow', Arial, sans-serif;
  font-size: 12px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1.5px; color: #7ec8e3; margin-bottom: 10px; line-height: 1.4;
  border-bottom: 2px solid rgba(255,255,255,0.1); padding-bottom: 7px;
}}
.stat {{ margin-bottom: 9px; }}
.stat-lbl {{ font-size: 9px; color: #4a7a9a; text-transform: uppercase; letter-spacing: 1.5px; line-height: 1; }}
.stat-val {{
  font-family: 'Arial Black', Impact, sans-serif;
  font-size: 20px; font-weight: 900; color: #e0f0ff; line-height: 1.1;
}}
.stat-note {{ font-size: 11px; color: #5ba8cc; line-height: 1.3; }}

.bottom-table {{ width: 100%; border-collapse: separate; border-spacing: 8px; }}
.bottom-table td {{
  vertical-align: top;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px; padding: 14px;
}}
.syn-title {{ font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: #7ec8e3; margin-bottom: 8px; }}
.syn-text {{ font-size: 12.5px; color: #9ab8d0; line-height: 1.6; }}
.tags {{ margin-top: 10px; }}
.tag {{
  display: inline-block;
  background: rgba(160,20,20,0.25);
  border: 1px solid rgba(200,40,40,0.5);
  border-radius: 20px; padding: 4px 11px;
  font-size: 10.5px; color: #ff8888; letter-spacing: 0.8px; text-transform: uppercase; font-weight: 700;
  margin: 3px 3px 0 0;
}}

.footer {{
  background: rgba(0,0,0,0.4);
  border-top: 1px solid rgba(255,255,255,0.07);
  padding: 10px 28px;
}}
.footer table {{ width: 100%; border-collapse: collapse; }}
.footer-src {{ font-size: 11px; color: #3a5a7a; }}
.footer-url {{
  font-family: 'Arial Narrow', Arial, sans-serif;
  font-size: 17px; font-weight: 700; color: #1e88e5; letter-spacing: 1px; text-align: right;
}}
</style>
</head>
<body>
<div class="card"><div class="card-inner">

<div class="header">
  <table><tr>
    <td style="width:100px;"><img class="logo" src="data:image/jpeg;base64,{logo_b64}" /></td>
    <td style="padding-left:14px;">
      <div class="brand">Rabirubia Weather</div>
      <div class="sub">Marine Forecast &mdash; PR &amp; USVI</div>
    </td>
    <td style="width:220px;">
      <div class="date-big">{date_str}</div>
      <div class="date-small">AST</div>
    </td>
  </tr></table>
</div>

<div class="alert">⚠️ &nbsp; {advisory_text}</div>

<div class="grid">
<table class="grid-table"><tr>
  {zone_html(atl, 'z1', '🌊', 'Atlantic Offshore<br>(10NM &ndash; 19.5&deg;N)')}
  {zone_html(npr, 'z2', '🧭', 'Northern PR Coast<br>(out 10 NM)')}
  {zone_html(epr, 'z3', '⚓', 'East PR / Vieques<br>Culebra &amp; St. John')}
  {zone_html(car, 'z4', '🐟', 'Caribbean Waters<br>PR + St. Croix')}
</tr></table>
</div>

<div style="padding: 0 16px 8px;">
<table class="bottom-table"><tr>

  <td style="width:25%;">
    <div class="syn-title">📡 Swell Summary</div>
    <div class="stat">
      <div class="stat-lbl">🌐 Atlantic Swell</div>
      <div class="stat-val" style="font-size:18px;">{atl['seas']}</div>
      <div class="stat-note">{atl['wave_detail']}</div>
    </div>
    <div class="stat">
      <div class="stat-lbl">🔄 Caribbean Seas</div>
      <div class="stat-val" style="font-size:18px;">{car['seas']}</div>
      <div class="stat-note">{car['wave_detail']}</div>
    </div>
  </td>

  <td style="width:25%;">
    <div class="syn-title">⛅ Conditions</div>
    <div class="stat">
      <div class="stat-lbl">🌧 Precip</div>
      <div class="stat-note" style="font-size:12px; color:#9ab8d0;">{atl.get('precip','—') or '—'}</div>
    </div>
    <div class="stat">
      <div class="stat-lbl">🐟 Fishing</div>
      <div class="stat-note" style="font-size:12px; color:#9ab8d0;">
        {"Rough — offshore not recommended" if any(x in atl['seas'] for x in ['8','9','10','11','12']) else "Moderate — use caution"}
      </div>
    </div>
  </td>

  <td style="width:50%;">
    <div class="syn-title">📋 Synopsis</div>
    <div class="syn-text">{synopsis}</div>
    <div class="tags">{tags_html}</div>
  </td>

</tr></table>
</div>

<div class="footer">
  <table><tr>
    <td class="footer-src">Source: NWS San Juan &middot; NOAA</td>
    <td class="footer-url">www.rabirubiaweather.com</td>
  </tr></table>
</div>

</div></div>
</body>
</html>"""


# ─────────────────────────────────────────────
# Render HTML → JPG
# ─────────────────────────────────────────────
def render_jpg(html: str, output_path: Path) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        tmp_html = f.name

    tmp_jpg = str(output_path).replace(".jpg", "_raw.jpg")

    try:
        result = subprocess.run(
            ["wkhtmltoimage", "--width", "1080", "--height", "1080",
             "--quality", "95", "--log-level", "none", tmp_html, tmp_jpg],
            capture_output=True, text=True
        )

        if not Path(tmp_jpg).exists():
            print(f"ERROR: wkhtmltoimage failed: {result.stderr}", file=sys.stderr)
            return False

        # Crop to content and scale to exact 1080x1080
        try:
            from PIL import Image
            img = Image.open(tmp_jpg)
            w, h = img.size
            crop_h = min(720, h)
            cropped = img.crop((0, 0, 1080, crop_h))
            final = cropped.resize((1080, 1080), Image.LANCZOS)
            final.save(str(output_path), "JPEG", quality=95)
            print(f"  ✓ Saved: {output_path}")
        except ImportError:
            # No PIL — just move the raw file
            import shutil
            shutil.move(tmp_jpg, str(output_path))
            print(f"  ✓ Saved (no crop): {output_path}")

        return True

    finally:
        try:
            os.unlink(tmp_html)
            if Path(tmp_jpg).exists():
                os.unlink(tmp_jpg)
        except Exception:
            pass


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    now = datetime.now()
    date_str = now.strftime("%b %d").upper()   # e.g. "FEB 27"
    file_date = now.strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"rabirubia_marine_{file_date}.jpg"
    latest_file = OUTPUT_DIR / "rabirubia_marine_latest.jpg"

    print(f"\n🌊 Rabirubia Weather Card Generator")
    print(f"   Date: {date_str}")
    print(f"   Output: {output_file}\n")

    # Load logo
    logo_b64_path = SCRIPT_DIR / "logo_b64.txt"
    if logo_b64_path.exists():
        logo_b64 = logo_b64_path.read_text().strip()
    else:
        print("  WARNING: logo_b64.txt not found — logo will be missing", file=sys.stderr)
        logo_b64 = ""

    # Fetch all zones
    print("📡 Fetching NWS forecasts...")
    raw = {}
    for name, url in NWS_ZONES.items():
        print(f"   → {name}")
        raw[name] = fetch_nws(url)

    # Parse zones
    print("\n🔍 Parsing forecast data...")
    zones = {name: parse_zone(text) for name, text in raw.items()}

    # Use synopsis zone for the synopsis text
    if zones["synopsis"].get("synopsis"):
        zones["atlantic"]["synopsis"] = zones["synopsis"]["synopsis"]

    # Debug output
    for name, z in zones.items():
        if name == "synopsis":
            continue
        print(f"   {name}: wind={z['wind']} | seas={z['seas']} | gusts={z['gusts']}")

    # Build HTML
    print("\n🎨 Building card HTML...")
    html = build_html(zones, date_str, logo_b64)

    # Render
    print("\n🖼  Rendering image...")
    success = render_jpg(html, output_file)

    if success:
        # Also save as "latest" for easy reference
        import shutil
        shutil.copy(str(output_file), str(latest_file))
        print(f"  ✓ Latest copy: {latest_file}")
        print("\n✅ Done!\n")
    else:
        print("\n❌ Render failed.\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
