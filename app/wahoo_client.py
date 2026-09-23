import logging
import os
import time
import requests
from urllib.parse import quote

logger = logging.getLogger("wahoo_connector.wahoo_client")

WAHOO_AUTH_URL = "https://api.wahooligan.com/oauth/authorize"
WAHOO_TOKEN_URL = "https://api.wahooligan.com/oauth/token"
WAHOO_API_BASE = "https://api.wahooligan.com/v1"

class RateLimiter:
    """
    Dynamic Header-Based Rate Limiter for Wahoo Cloud API.
    Reads official Wahoo response headers:
    - X-RateLimit-Limit: <day>, <hour>, <5min>
    - X-RateLimit-Remaining: <remaining_day>, <remaining_hour>, <remaining_5min>
    - X-RateLimit-Reset: <seconds>
    """
    def __init__(self):
        self.remaining_5min = 25
        self.remaining_hour = 100
        self.remaining_day = 250
        self.reset_seconds = 0
        self.last_response_time = 0

    def update_from_headers(self, headers: dict):
        """Update rate limits dynamically from Wahoo API response headers."""
        remaining_header = headers.get("X-RateLimit-Remaining") or headers.get("x-ratelimit-remaining")
        reset_header = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")

        if remaining_header:
            try:
                parts = [int(p.strip()) for p in remaining_header.split(",")]
                if len(parts) >= 3:
                    self.remaining_day = parts[0]
                    self.remaining_hour = parts[1]
                    self.remaining_5min = parts[2]
                elif len(parts) == 1:
                    self.remaining_5min = parts[0]

                logger.debug(
                    f"Dynamic RateLimit -> 5Min: {self.remaining_5min}, Hour: {self.remaining_hour}, Day: {self.remaining_day}"
                )
            except Exception as e:
                logger.debug(f"Could not parse X-RateLimit-Remaining header '{remaining_header}': {e}")

        if reset_header:
            try:
                self.reset_seconds = int(reset_header)
            except Exception:
                pass

        self.last_response_time = time.time()

    def wait_if_needed(self):
        """Enforce minimum spacing and pause if server quota is low."""
        # 1. Minimum 1.0s spacing between API requests to prevent burst limiters
        time.sleep(1.0)

        # 2. Check server-provided remaining quota
        if self.remaining_5min <= 2 or self.remaining_hour <= 5 or self.remaining_day <= 5:
            wait_time = max(self.reset_seconds, 5)
            logger.warning(
                f"Wahoo API quota nearly exhausted (5Min: {self.remaining_5min}, Hour: {self.remaining_hour}, Day: {self.remaining_day}). "
                f"Pausing execution for {wait_time}s until reset..."
            )
            time.sleep(wait_time)
            # Reset optimistic estimates after waiting
            self.remaining_5min = 25

class WahooClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id.strip() if client_id else ""
        self.client_secret = client_secret.strip() if client_secret else ""
        self.redirect_uri = redirect_uri.strip() if redirect_uri else ""
        self.rate_limiter = RateLimiter()

    def get_auth_url(self, scopes: list = None) -> str:
        """Generate Wahoo OAuth2 Authorization URL with space-separated scopes."""
        if scopes is None:
            scopes_env = os.getenv("WAHOO_SCOPES", "user_read workouts_read")
            scopes = [s.strip() for s in scopes_env.split() if s.strip()]

        scope_str = "%20".join(scopes)
        redirect_encoded = quote(self.redirect_uri, safe="")

        return (
            f"{WAHOO_AUTH_URL}?"
            f"client_id={self.client_id}&"
            f"redirect_uri={redirect_encoded}&"
            f"response_type=code&"
            f"scope={scope_str}"
        )

    def exchange_code_for_tokens(self, code: str) -> dict:
        """Exchange authorization code for access and refresh tokens."""
        self.rate_limiter.wait_if_needed()
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri
        }
        logger.info("Exchanging authorization code for tokens at Wahoo API...")
        response = requests.post(
            WAHOO_TOKEN_URL,
            data=payload,
            timeout=30
        )
        self.rate_limiter.update_from_headers(response.headers)
        if not response.ok:
            logger.error(f"Token exchange failed ({response.status_code}): {response.text}")
            response.raise_for_status()
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> dict:
        """Refresh expired access token using refresh_token."""
        self.rate_limiter.wait_if_needed()
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        logger.info("Refreshing access token at Wahoo API...")
        response = requests.post(
            WAHOO_TOKEN_URL,
            data=payload,
            timeout=30
        )
        self.rate_limiter.update_from_headers(response.headers)
        if not response.ok:
            logger.error(f"Token refresh failed ({response.status_code}): {response.text}")
            response.raise_for_status()
        return response.json()

    def get_user_profile(self, access_token: str) -> dict:
        """Fetch authenticated user profile information."""
        self.rate_limiter.wait_if_needed()
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(f"{WAHOO_API_BASE}/user", headers=headers, timeout=30)
        self.rate_limiter.update_from_headers(response.headers)
        if not response.ok:
            logger.error(f"User profile fetch failed ({response.status_code}): {response.text}")
            response.raise_for_status()
        return response.json()

    def fetch_workouts(self, access_token: str, page: int = 1, per_page: int = 50) -> dict:
        """
        Fetch workouts for the user in DESCENDING order (newest workouts first).
        The Wahoo /v1/workouts endpoint returns workouts sorted by starts in
        descending order by default and does not accept an "order" query param.
        Endpoint: GET https://api.wahooligan.com/v1/workouts
        """
        self.rate_limiter.wait_if_needed()
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {
            "page": page,
            "per_page": per_page
        }
        logger.info(f"Fetching workouts page {page} (per_page={per_page})...")
        response = requests.get(f"{WAHOO_API_BASE}/workouts", headers=headers, params=params, timeout=30)
        self.rate_limiter.update_from_headers(response.headers)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning(f"Wahoo API returned 429 Too Many Requests. Retrying in {retry_after} seconds...")
            time.sleep(retry_after)
            self.rate_limiter.wait_if_needed()
            response = requests.get(f"{WAHOO_API_BASE}/workouts", headers=headers, params=params, timeout=30)
            self.rate_limiter.update_from_headers(response.headers)

        if not response.ok:
            logger.error(f"Workouts fetch failed ({response.status_code}): {response.text}")
            response.raise_for_status()
        return response.json()

    def download_file(self, file_url: str, dest_path: str) -> bool:
        """
        Download binary workout file (e.g. .FIT) from Wahoo CDN.
        Uses atomic file writing (.tmp -> .fit) so file watchers (like Dreeve) 
        only trigger when the download is 100% complete.
        """
        tmp_path = dest_path + ".tmp"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        logger.info(f"Downloading FIT file from CDN -> {dest_path}")
        response = requests.get(file_url, headers=headers, stream=True, timeout=60)
        if not response.ok:
            logger.error(f"File download failed ({response.status_code}): {response.text}")
            response.raise_for_status()

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        try:
            os.chmod(tmp_path, 0o666)
        except Exception:
            pass

        os.replace(tmp_path, dest_path)
        return True
