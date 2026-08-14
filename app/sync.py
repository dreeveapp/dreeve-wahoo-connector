import json
import logging
import os
import time
from datetime import datetime, timedelta
from app.wahoo_client import WahooClient

logger = logging.getLogger("wahoo_connector.sync")

def get_data_paths():
    data_dir = os.getenv("DATA_DIR", "/data")
    config_dir = os.getenv("STATE_DIR") or os.path.join(data_dir, "config")
    downloads_dir = os.getenv("WATCH_DIR") or os.getenv("DOWNLOADS_DIR") or os.path.join(data_dir, "downloads")
    
    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(downloads_dir, exist_ok=True)

    return {
        "tokens": os.path.join(config_dir, "tokens.json"),
        "history": os.path.join(config_dir, "sync_history.json"),
        "downloads": downloads_dir
    }

def load_tokens() -> dict:
    paths = get_data_paths()
    if os.path.exists(paths["tokens"]):
        try:
            with open(paths["tokens"], "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading tokens file: {e}")
    return {}

def save_tokens(tokens: dict):
    paths = get_data_paths()
    if "expires_in" in tokens and "expires_at" not in tokens:
        tokens["expires_at"] = int(time.time()) + int(tokens["expires_in"])

    with open(paths["tokens"], "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    logger.info("Tokens successfully saved to disk.")

def load_history() -> dict:
    paths = get_data_paths()
    if os.path.exists(paths["history"]):
        try:
            with open(paths["history"], "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading sync history file: {e}")
    return {"downloaded": {}, "last_sync": None}

def save_history(history: dict):
    paths = get_data_paths()
    history["last_sync"] = datetime.utcnow().isoformat() + "Z"
    with open(paths["history"], "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

def get_all_activities() -> list:
    """
    Scan disk downloads folder and merge with sync_history.json
    to ensure 100% of downloaded workouts are accurately listed in the Web UI,
    even if downstream consumers (like Dreeve) move/delete files from the watch folder.
    """
    paths = get_data_paths()
    history = load_history()
    downloaded_map = history.get("downloaded", {})
    activities = []

    disk_files = {}
    if os.path.exists(paths["downloads"]):
        for fn in os.listdir(paths["downloads"]):
            if fn.endswith(".fit"):
                file_path = os.path.join(paths["downloads"], fn)
                size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                disk_files[fn] = size_bytes

    seen_ids = set()

    # Process all workouts recorded in history
    for workout_id, hist_entry in downloaded_map.items():
        str_id = str(workout_id)
        seen_ids.add(str_id)
        fn = hist_entry.get("filename") or f"workout_{str_id}.fit"
        
        if fn in disk_files:
            size_bytes = disk_files[fn]
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = "N/A (Processed)"

        starts = hist_entry.get("starts") or "N/A"
        downloaded_at = hist_entry.get("downloaded_at")

        activities.append({
            "id": str_id,
            "starts": starts,
            "filename": fn,
            "downloaded_at": downloaded_at,
            "size_str": size_str
        })

    # Add any disk files that were not in sync_history
    for fn, size_bytes in disk_files.items():
        workout_id = fn.replace(".fit", "")
        workout_date = "N/A"
        
        if "_workout_" in fn:
            parts = fn.split("_workout_")
            workout_date = parts[0]
            workout_id = parts[1].replace(".fit", "")

        str_id = str(workout_id)
        if str_id in seen_ids:
            continue

        seen_ids.add(str_id)
        file_path = os.path.join(paths["downloads"], fn)
        downloaded_at = None
        if os.path.exists(file_path):
            mtime = os.path.getmtime(file_path)
            downloaded_at = datetime.utcfromtimestamp(mtime).isoformat() + "Z"

        activities.append({
            "id": str_id,
            "starts": workout_date,
            "filename": fn,
            "downloaded_at": downloaded_at,
            "size_str": f"{size_bytes / 1024:.1f} KB"
        })

    activities.sort(key=lambda x: x.get("starts", ""), reverse=True)
    return activities

def get_cutoff_datetime(time_window: str):
    """Calculate datetime cutoff based on selected time window."""
    if not time_window or time_window == "all_time":
        return None

    now = datetime.utcnow()
    if time_window == "1_day":
        return now - timedelta(days=1)
    elif time_window == "1_week":
        return now - timedelta(days=7)
    elif time_window == "1_month":
        return now - timedelta(days=30)
    elif time_window == "1_year":
        return now - timedelta(days=365)

    return None

def extract_fit_url(workout: dict) -> str:
    """Extract .FIT download URL from various possible fields in Wahoo workout response."""
    summary = workout.get("workout_summary")
    if isinstance(summary, dict):
        f = summary.get("file")
        if isinstance(f, dict) and f.get("url"):
            return f.get("url")

    f = workout.get("file")
    if isinstance(f, dict) and f.get("url"):
        return f.get("url")

    if workout.get("file_url"):
        return workout.get("file_url")

    return None

def perform_sync(time_window: str = None) -> dict:
    """
    Main sync logic with Time Selector filtering (defaults to 1_week):
    1. Verify / refresh tokens
    2. Fetch workouts from Wahoo API in DESCENDING order (newest first)
    3. Filter by selected time window (1_day, 1_week, 1_month, 1_year, all_time)
    4. Check local history & disk for deduplication
    5. Download missing FIT files
    """
    if not time_window:
        time_window = os.getenv("SYNC_TIME_WINDOW", "1_week")

    client_id = os.getenv("WAHOO_CLIENT_ID")
    client_secret = os.getenv("WAHOO_CLIENT_SECRET")
    redirect_uri = os.getenv("WAHOO_REDIRECT_URI", "https://localhost:8085/callback")

    if not client_id or not client_secret:
        return {"status": "error", "message": "WAHOO_CLIENT_ID and WAHOO_CLIENT_SECRET must be set in environment."}

    client = WahooClient(client_id, client_secret, redirect_uri)
    tokens = load_tokens()

    if not tokens or "access_token" not in tokens:
        return {"status": "error", "message": "Not authenticated with Wahoo yet. Please complete OAuth login via Web UI."}

    expires_at = tokens.get("expires_at", 0)
    current_time = int(time.time())

    if current_time > (expires_at - 300):
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            return {"status": "error", "message": "Access token expired and no refresh token available. Please re-authenticate."}
        
        logger.info("Access token expired or expiring soon. Refreshing token...")
        try:
            new_tokens = client.refresh_access_token(refresh_token)
            if "refresh_token" not in new_tokens:
                new_tokens["refresh_token"] = refresh_token
            save_tokens(new_tokens)
            tokens = new_tokens
        except Exception as e:
            logger.error(f"Failed to refresh access token: {e}")
            return {"status": "error", "message": f"Failed to refresh access token: {str(e)}"}

    access_token = tokens["access_token"]
    paths = get_data_paths()
    history = load_history()
    downloaded_map = history.get("downloaded", {})

    cutoff_dt = get_cutoff_datetime(time_window)
    if cutoff_dt:
        logger.info(f"Filtering sync to time window: {time_window} (Cutoff: {cutoff_dt.isoformat()}Z)")

    page = 1
    per_page = 50
    total_new = 0
    total_skipped = 0
    total_processed = 0
    errors = []
    stop_sync = False

    logger.info(f"Starting Wahoo workout sync (time_window={time_window})...")

    while not stop_sync:
        try:
            data = client.fetch_workouts(access_token, page=page, per_page=per_page, order="descending")
        except Exception as e:
            logger.error(f"Error fetching workouts page {page}: {e}")
            errors.append(f"Page {page} fetch error: {str(e)}")
            break

        workouts = []
        if isinstance(data, dict):
            workouts = data.get("workouts", [])
        elif isinstance(data, list):
            workouts = data

        if not workouts:
            logger.info("No more workouts returned from API.")
            break

        consecutive_existing_count = 0

        for workout in workouts:
            total_processed += 1
            workout_id = str(workout.get("id"))
            starts_str = workout.get("starts") or workout.get("created_at") or workout.get("workout_summary", {}).get("starts") or ""
            
            starts_dt = None
            date_prefix = "workout"
            if starts_str:
                try:
                    starts_dt = datetime.fromisoformat(starts_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    date_prefix = starts_dt.strftime("%Y-%m-%d")
                except Exception:
                    date_prefix = starts_str[:10]

            if cutoff_dt and starts_dt and starts_dt < cutoff_dt:
                logger.info(f"Workout {workout_id} ({starts_str}) is older than cutoff {cutoff_dt.isoformat()}Z. Time window limit reached.")
                stop_sync = True
                break

            filename = f"{date_prefix}_workout_{workout_id}.fit"
            dest_path = os.path.join(paths["downloads"], filename)

            verify_disk = os.getenv("VERIFY_FILES_ON_DISK", "false").lower() in ["true", "1", "yes"]
            is_already_downloaded = (workout_id in downloaded_map) and (not verify_disk or os.path.exists(dest_path))

            if is_already_downloaded:
                total_skipped += 1
                consecutive_existing_count += 1
                logger.debug(f"Workout {workout_id} ({filename}) already downloaded. Skipping.")
                continue

            consecutive_existing_count = 0
            fit_url = extract_fit_url(workout)
            if not fit_url:
                logger.warning(f"Workout {workout_id} does not have a FIT file URL available. Skipping.")
                continue

            try:
                client.download_file(fit_url, dest_path)
                downloaded_map[workout_id] = {
                    "id": workout_id,
                    "starts": starts_str,
                    "filename": filename,
                    "downloaded_at": datetime.utcnow().isoformat() + "Z"
                }
                total_new += 1
                logger.info(f"Successfully downloaded new workout {workout_id} -> {filename}")
            except Exception as e:
                logger.error(f"Failed to download FIT file for workout {workout_id}: {e}")
                errors.append(f"Workout {workout_id} download error: {str(e)}")

        if stop_sync:
            break

        if consecutive_existing_count >= len(workouts) and len(workouts) > 0:
            logger.info("Encountered fully synced page of existing workouts. Incremental sync complete!")
            break

        if len(workouts) < per_page:
            break
        page += 1

    history["downloaded"] = downloaded_map
    save_history(history)

    result = {
        "status": "success" if not errors else "partial_success",
        "new_downloads": total_new,
        "skipped": total_skipped,
        "total_processed": total_processed,
        "time_window": time_window,
        "errors": errors,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    logger.info(f"Sync complete ({time_window}). New downloads: {total_new}, Skipped: {total_skipped}, Errors: {len(errors)}")
    return result
