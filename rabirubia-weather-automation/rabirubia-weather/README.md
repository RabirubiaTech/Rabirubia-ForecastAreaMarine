# 🌊 Rabirubia Weather Card — Daily Automation

Automatically generates a daily Instagram-ready marine weather image (1080×1080 JPG)
for Puerto Rico & USVI waters every morning at **6:30 AM AST** using free GitHub Actions.

No server needed. No cost. Runs automatically every day.

---

## 📁 Project Structure

```
rabirubia-weather/
├── .github/
│   └── workflows/
│       └── daily_weather.yml   ← Automation schedule (runs 6:30am AST daily)
├── scripts/
│   ├── generate_card.py        ← Main script that fetches & renders the card
│   └── logo_b64.txt            ← Your logo embedded as base64
├── output/                     ← Generated images land here
├── requirements.txt
└── README.md
```

---

## 🚀 Setup Guide (One-Time, ~10 Minutes)

### Step 1 — Create a GitHub Account
If you don't have one: go to **https://github.com** and sign up (free).

---

### Step 2 — Create a New Repository

1. Click the **+** icon (top right) → **New repository**
2. Name it: `rabirubia-weather`
3. Set to **Public** (required for free Actions minutes)
4. Click **Create repository**

---

### Step 3 — Upload All the Files

You can do this directly in the browser:

1. On your new repo page, click **"uploading an existing file"** or **Add file → Upload files**
2. Upload **all files and folders** from this ZIP package, keeping the folder structure:
   ```
   .github/workflows/daily_weather.yml
   scripts/generate_card.py
   scripts/logo_b64.txt
   requirements.txt
   ```
3. Click **Commit changes**

> 💡 **Alternative:** Use GitHub Desktop (free app) to drag-and-drop the whole folder.

---

### Step 4 — Enable GitHub Actions

1. Go to your repo → click the **Actions** tab
2. If prompted, click **"I understand my workflows, go ahead and enable them"**
3. You'll see **"Daily Marine Weather Card"** in the list

---

### Step 5 — Test It Right Now

Don't wait until 6:30 AM — run it manually:

1. Go to **Actions** tab
2. Click **"Daily Marine Weather Card"** on the left
3. Click the **"Run workflow"** button (top right of the table)
4. Click the green **"Run workflow"** button
5. Wait ~2 minutes — you'll see a green checkmark ✅

---

### Step 6 — Find Your Image

After it runs:

**Option A — Download from Actions:**
1. Click the completed workflow run
2. Scroll down to **Artifacts**
3. Click **marine-weather-card-XXXXX** to download the JPG

**Option B — In the repo:**
The image is committed automatically to the `output/` folder.
Go to **Code** tab → `output/` → `rabirubia_marine_latest.jpg` → click **Download**

---

## ⏰ Schedule

The card is generated every day at **6:30 AM AST** (10:30 AM UTC).

To change the time, edit `.github/workflows/daily_weather.yml`:
```yaml
- cron: "30 10 * * *"   # UTC time — AST is UTC-4
```

Common times (all UTC):
| AST Time | UTC cron |
|----------|----------|
| 5:00 AM  | `0 9 * * *` |
| 6:00 AM  | `0 10 * * *` |
| 6:30 AM  | `30 10 * * *` |
| 7:00 AM  | `0 11 * * *` |

---

## 🌊 Weather Data Sources

Data is fetched directly from **NOAA / NWS San Juan** — no API keys needed:

| Zone | NWS Code | Description |
|------|----------|-------------|
| Atlantic Offshore | AMZ711 | Atlantic Waters of PR & USVI, 10NM to 19.5°N |
| Northern PR Coast | AMZ712 | Coastal Waters of Northern Puerto Rico out 10 NM |
| East PR / USVI | AMZ726 | East PR, Vieques, Culebra, St. John |
| Caribbean / St. Croix | AMZ733 | Caribbean Waters of PR, 10NM to 17N, St. Croix |

---

## 🔄 To Update Your Logo

1. Convert your logo JPG to base64:
   ```bash
   python3 -c "import base64; print(base64.b64encode(open('logo.jpg','rb').read()).decode())" > scripts/logo_b64.txt
   ```
2. Commit and push `scripts/logo_b64.txt`

---

## 📱 Posting to Instagram Automatically (Optional Advanced Step)

To auto-post to Instagram, you need Meta's Instagram Graph API.
This requires a **Facebook Business account** and **Instagram Professional account**.

Add these secrets to your GitHub repo (Settings → Secrets → Actions):
- `INSTAGRAM_ACCESS_TOKEN`
- `INSTAGRAM_ACCOUNT_ID`

Then add this step to `daily_weather.yml` after the image is generated:
```yaml
- name: Post to Instagram
  run: python scripts/post_instagram.py
  env:
    INSTAGRAM_ACCESS_TOKEN: ${{ secrets.INSTAGRAM_ACCESS_TOKEN }}
    INSTAGRAM_ACCOUNT_ID: ${{ secrets.INSTAGRAM_ACCOUNT_ID }}
```

Contact us at www.rabirubiaweather.com for help with this step.

---

## 🛠 Run It Locally (on your own computer)

### Prerequisites
- Python 3.8+
- `wkhtmltoimage` installed:
  - **Mac:** `brew install wkhtmltopdf`
  - **Windows:** Download from https://wkhtmltopdf.org/downloads.html
  - **Linux:** `sudo apt install wkhtmltopdf`

### Run
```bash
pip install Pillow
python scripts/generate_card.py
```

The image will be saved to `output/rabirubia_marine_latest.jpg`.

### Schedule on your Mac (cron)
```bash
crontab -e
# Add this line:
30 6 * * * cd /path/to/rabirubia-weather && python3 scripts/generate_card.py
```

### Schedule on Windows (Task Scheduler)
1. Open Task Scheduler → Create Basic Task
2. Set trigger: Daily at 6:30 AM
3. Action: Start a program → `python.exe`
4. Arguments: `C:\path\to\scripts\generate_card.py`

---

## ❓ Troubleshooting

**Image is blank or missing data:**
NOAA servers are occasionally slow. The script will print warnings for any failed fetches.
Re-run the workflow manually.

**wkhtmltoimage not found:**
The GitHub Actions workflow installs it automatically. For local runs, see Prerequisites above.

**Wrong time zone:**
GitHub Actions runs in UTC. The cron `30 10 * * *` = 6:30 AM AST (UTC-4).
During EST (UTC-5), adjust to `30 11 * * *` if needed (PR doesn't observe DST).

---

## 📞 Support

**www.rabirubiaweather.com**
