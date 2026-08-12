<p align="center">
  <img src="assets/logo.jpg" alt="dreeve-wahoo-connector Logo" width="180" style="border-radius: 24px;" />
</p>

<h1 align="center">dreeve-wahoo-connector</h1>

<p align="center">
  <strong style="font-size: 1.1em;">Self-hosted tool to download Wahoo workouts into Dreeve.</strong>
</p>

<p align="center">
  <a href="https://github.com/dreeveapp/dreeve-wahoo-connector/actions"><img src="https://github.com/dreeveapp/dreeve-wahoo-connector/workflows/Build%20and%20Publish%20Docker%20Image%20to%20GHCR/badge.svg" alt="Build Status"></a>
  <a href="https://github.com/dreeveapp/dreeve-wahoo-connector/pkgs/container/dreeve-wahoo-connector"><img src="https://img.shields.io/badge/Docker-GHCR-blue?logo=docker" alt="GHCR Docker Image"></a>
  <a href="https://github.com/dreeveapp/dreeve-wahoo-connector/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License"></a>
</p>

---

`dreeve-wahoo-connector` is a lightweight, containerized tool that connects to the [Wahoo Fitness Cloud API](https://developers.wahooligan.com/) to automatically download your workout activities as standard `.FIT` files into a local directory on your server or NAS.

It features **incremental syncing**, **smart deduplication**, **dynamic HTTP header rate limiting**, **daily cron scheduling**, and **atomic file writing** for seamless integration with self-hosted fitness dashboards like [Dreeve](https://github.com/dreeveapp/dreeve).

---

## 🌟 Key Features

* 🚴 **Automatic Wahoo OAuth Sync**: Authenticates via Wahoo Cloud API (`user_read workouts_read`) and downloads binary `.FIT` workout files.
* ⏱️ **Time Window Selector**: Sync workouts from the last 1 Day, 1 Week, 1 Month, 1 Year, or All Time directly from the web interface.
* ⏰ **Cron & Interval Scheduler**: Configurable 5-field cron syntax (`SYNC_CRON=0 2 * * *`) for automated daily background downloads.
* ⚡ **Dynamic Header Rate Limiter**: Monitors Wahoo API `X-RateLimit-Remaining` HTTP response headers in real time to prevent rate-limit errors (`429`).
* 🔄 **Smart Deduplication**: Queries workouts in descending order (newest first) and stops early on previously downloaded activities to save API requests.
* 🧩 **Dreeve / Watch Folder Integration**: Implements atomic file writing (`.tmp` $\rightarrow$ `.fit`) so fitness tracking dashboards (like Dreeve) can safely watch and import new workouts.
* 🎨 **Glassmorphism Web Dashboard**: Includes a modern HTTPS web interface on port 8085 with live status auto-polling every 3 seconds.
* 🐳 **Docker & Unraid Ready**: Pre-configured with `Dockerfile`, `docker-compose.yml`, and GitHub Container Registry (`ghcr.io/dreeveapp/dreeve-wahoo-connector:latest`).

---

## 🚀 Quick Start Guide

### Step 1: Register Wahoo Developer Application

1. Go to the [Wahoo Developer Portal](https://developers.wahooligan.com/applications) and sign in.
2. Click **Create Application**.
3. Fill in the required fields:
   * **App Name**: `dreeve-wahoo-connector` (or your preferred name)
   * **Redirect URI**: `https://<YOUR-SERVER-IP>:8085/callback` *(e.g. `https://192.168.1.100:8085/callback`)*
   * **Webhook URI**: Leave blank
4. Submit the application and copy your **Client ID** and **Client Secret**.

---

### Step 2: Configure Environment Variables

Create or edit the `.env` file in the project root:

```ini
WAHOO_CLIENT_ID=your_client_id_here
WAHOO_CLIENT_SECRET=your_client_secret_here
WAHOO_REDIRECT_URI=https://192.168.1.100:8085/callback
SYNC_TIME_WINDOW=1_week
SYNC_CRON=0 2 * * *
PORT=8085
```

---

### Step 3: Run with Docker Compose

```yaml
services:
  dreeve-wahoo-connector:
    image: ghcr.io/dreeveapp/dreeve-wahoo-connector:latest
    container_name: dreeve-wahoo-connector
    restart: unless-stopped
    ports:
      - "8085:8080"
    env_file:
      - .env
    volumes:
      - ./config:/data/config
      - ./activities:/data/downloads
```

Start the container:

```bash
docker compose up -d
```

---

### Step 4: One-Click Authentication

1. Open your web browser and navigate to **`https://<YOUR-SERVER-IP>:8085`**.
2. Accept the self-signed SSL certificate in your browser if prompted.
3. Click **Connect Wahoo Account**.
4. Authorize the application on Wahoo's website.
5. You will be redirected back to the dashboard, and `dreeve-wahoo-connector` will immediately perform its initial sync!

All downloaded `.FIT` files will be saved in the `./activities` folder on your host machine.

---

## ⚙️ Configuration Options

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `WAHOO_CLIENT_ID` | *Required* | Client ID from Wahoo Developer Portal |
| `WAHOO_CLIENT_SECRET` | *Required* | Client Secret from Wahoo Developer Portal |
| `WAHOO_REDIRECT_URI` | `https://localhost:8085/callback` | OAuth redirect URI matching Wahoo App settings |
| `SYNC_TIME_WINDOW` | `1_week` | Default sync timeframe (`1_day`, `1_week`, `1_month`, `1_year`, `all_time`) |
| `SYNC_CRON` | `0 2 * * *` | 5-field Cron schedule for auto-syncing (default: daily at 02:00 UTC) |
| `PORT` | `8085` | Port for web server dashboard & OAuth callback |
| `DATA_DIR` | `/data` | Internal container path for config and downloads |

---

## 📁 Directory Structure

```text
dreeve-wahoo-connector/
├── assets/
│   └── logo.jpg           # Project branding logo
├── activities/            # Local directory where .FIT files are saved
│   ├── 2026-07-28_workout_1234567.fit
│   └── 2026-07-25_workout_1234566.fit
├── config/                # Persistent authentication tokens & sync history
│   ├── tokens.json
│   └── sync_history.json
├── app/
│   ├── __init__.py
│   ├── main.py            # Flask Web UI & server routes
│   ├── scheduler.py       # Cron & interval background scheduler
│   ├── sync.py            # Incremental sync & deduplication logic
│   └── wahoo_client.py    # Wahoo API client with dynamic header rate limiting
├── .env                   # Local configuration
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## 🧪 License

GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE) for details.
