
#!/usr/bin/env python3
"""
Nexthour V2Ray/VLESS configs -> GitHub Gist

Fetches all V2Ray servers from Nexthour API,
gets their configs and updates an existing GitHub Gist.

Required GitHub Actions secrets:
    GIST_TOKEN
    GIST_ID

Nexthour credentials are stored below in this file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


# ==================================================
# NEXTHOUR SETTINGS
# ==================================================

BASE = "https://api.nexthour.app"

API_KEY = "M7xE_IGzlrwjYm42CWvO28cxTztF0oW7"

PKG = "com.gamenetvpn.pingbooster"

CERT = (
    "31518fe51e27b0ce897e96fd2fc7538762f72b1b83337e4daeb11bd2762709f3"
)

KEY = bytes.fromhex(
    "72666839426c69546d4c794e5a793353"
    "585747477454367551514a6955357950"
    "3152744f4e2d5875414c595365645978"
)

EMPTY_SHA = hashlib.sha256(b"").hexdigest()


# ==================================================
# GITHUB GIST SETTINGS
# ==================================================

GITHUB_TOKEN = os.environ.get("GIST_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")

GIST_LINKS = "nexthour_v2ray_links.txt"
GIST_JSON = "nexthour_v2ray_configs.json"

# Save files locally when running in Termux.
# In GitHub Actions they will also be generated,
# but are not committed to the repository.
SAVE_LOCAL = True


# ==================================================
# HTTP CLIENT
# ==================================================

class Client:

    def __init__(self) -> None:
        self.device_id = (
            "android-" + uuid.uuid4().hex[:16]
        )

        self.session_token: str | None = None

    def _ts(self) -> str:
        """
        Get Nexthour server timestamp.

        If the API does not return x-server-time,
        use local Unix time.
        """

        now = str(int(time.time()))

        headers = {
            "Accept": "application/json",
            "User-Agent": "okhttp/4.12.0",
            "X-Api-Key": API_KEY,
            "X-Timestamp": now,
            "X-Signature": "0" * 64,
            "X-Device-Id": self.device_id,
            "X-App-Package": PKG,
        }

        req = urllib.request.Request(
            f"{BASE}/api/config",
            headers=headers,
        )

        try:
            with urllib.request.urlopen(
                req,
                timeout=10,
            ) as r:

                server_time = r.headers.get(
                    "x-server-time"
                )

                if server_time:
                    return str(server_time)

        except urllib.error.HTTPError as e:

            server_time = e.headers.get(
                "x-server-time"
            )

            if server_time:
                return str(server_time)

        except Exception:
            pass

        return now

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
    ) -> tuple[int, Any]:

        # ------------------------------------------
        # Prepare request body
        # ------------------------------------------

        if body is None:

            raw = None
            body_sha = EMPTY_SHA

        else:

            raw = json.dumps(
                body,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")

            body_sha = hashlib.sha256(
                raw
            ).hexdigest()

        # ------------------------------------------
        # Timestamp
        # ------------------------------------------

        timestamp = self._ts()

        # ------------------------------------------
        # Signature
        # ------------------------------------------

        canonical = (
            f"{method.upper()}\n"
            f"{path}\n"
            f"{timestamp}\n"
            f"{body_sha}\n"
            f"{CERT}"
        )

        signature = hmac.new(
            KEY,
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # ------------------------------------------
        # Headers
        # ------------------------------------------

        headers = {
            "Accept": "application/json",
            "User-Agent": "okhttp/4.12.0",
            "X-App-Package": PKG,
            "X-App-Version-Code": "1",
            "X-Device-Id": self.device_id,
            "X-Api-Key": API_KEY,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "X-App-Signature": CERT,
        }

        if self.session_token:
            headers["X-Session-Token"] = (
                self.session_token
            )

        if raw is not None:
            headers["Content-Type"] = (
                "application/json"
            )

        # ------------------------------------------
        # Request
        # ------------------------------------------

        req = urllib.request.Request(
            f"{BASE}{path}",
            data=raw,
            headers=headers,
            method=method.upper(),
        )

        try:

            with urllib.request.urlopen(
                req,
                timeout=30,
            ) as r:

                data = r.read()

                try:
                    data = json.loads(data)

                except Exception:
                    data = data.decode(
                        "utf-8",
                        "replace",
                    )

                return r.status, data

        except urllib.error.HTTPError as e:

            data = e.read()

            try:
                data = json.loads(data)

            except Exception:
                data = data.decode(
                    "utf-8",
                    "replace",
                )

            return e.code, data

        except Exception as e:

            return 0, str(e)

    def register(self) -> tuple[int, Any]:

        code, data = self.request(
            "POST",
            "/api/users/register-device",
            {
                "device_id": self.device_id,
                "platform": "android",
                "app_version": "1.0.0",
            },
        )

        if (
            code == 200
            and isinstance(data, dict)
        ):

            self.session_token = data.get(
                "session_token"
            )

        return code, data


# ==================================================
# FETCH CONFIGS
# ==================================================

def fetch_configs() -> list[dict[str, Any]]:

    client = Client()

    # ----------------------------------------------
    # Register device
    # ----------------------------------------------

    code, registration = client.register()

    print(f"register: {code}")

    if code != 200:

        print(
            "Registration response:",
            registration,
        )

    # ----------------------------------------------
    # Get servers
    # ----------------------------------------------

    code, servers = client.request(
        "GET",
        "/api/servers",
    )

    if (
        code != 200
        or not isinstance(servers, dict)
    ):

        raise RuntimeError(
            f"Failed to fetch servers: "
            f"HTTP {code}: {servers}"
        )

    items = servers.get("items") or []

    # Only V2Ray protocol
    v2ray_servers = [
        s
        for s in items
        if isinstance(s, dict)
        and (
            s.get("protocol") or ""
        ).lower() == "v2ray"
    ]

    print(
        f"V2Ray servers: "
        f"{len(v2ray_servers)}"
    )

    all_configs: list[dict[str, Any]] = []

    # ----------------------------------------------
    # Get config for every server
    # ----------------------------------------------

    for index, server in enumerate(
        v2ray_servers,
        start=1,
    ):

        sid = server.get("id")

        if not sid:
            continue

        country = server.get("country") or ""
        location = server.get("location") or ""

        print(
            f"[{index}/{len(v2ray_servers)}] "
            f"{country}/{location}"
        )

        code, data = client.request(
            "GET",
            f"/api/servers/{sid}/config",
        )

        if (
            code != 200
            or not isinstance(data, dict)
        ):

            print(
                f"  FAIL {sid}: "
                f"{code} {data}"
            )

            continue

        configs = data.get("configs") or []

        for cfg in configs:

            if not isinstance(cfg, dict):
                continue

            url = cfg.get("url") or ""

            if not url:
                continue

            entry = {
                "server_id": sid,
                "country": server.get("country"),
                "location": server.get("location"),
                "tier": server.get("tier"),
                "sub_protocol": data.get(
                    "sub_protocol"
                ),
                "config_id": cfg.get("id"),
                "url": url,
            }

            all_configs.append(entry)

            print(
                f"  {country}/{location}: "
                f"{url[:100]}..."
            )

    return all_configs


# ==================================================
# BUILD OUTPUT FILES
# ==================================================

def build_files(
    configs: list[dict[str, Any]],
) -> dict[str, str]:

    fetched_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(),
    )

    # ----------------------------------------------
    # JSON
    # ----------------------------------------------

    result = {
        "fetched_at": fetched_at,
        "count": len(configs),
        "configs": configs,
    }

    json_text = (
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    # ----------------------------------------------
    # TXT
    # ----------------------------------------------

    txt_lines: list[str] = []

    for entry in configs:

        country = entry.get("country") or ""
        location = entry.get("location") or ""
        tier = entry.get("tier") or ""

        txt_lines.append(
            f"# {country}/{location} tier={tier}"
        )

        txt_lines.append(
            entry["url"]
        )

        txt_lines.append("")

    txt_text = "\n".join(txt_lines)

    if (
        txt_text
        and not txt_text.endswith("\n")
    ):

        txt_text += "\n"

    return {
        GIST_JSON: json_text,
        GIST_LINKS: txt_text,
    }


# ==================================================
# SAVE LOCAL FILES
# ==================================================

def save_local_files(
    files: dict[str, str],
) -> None:

    if not SAVE_LOCAL:
        return

    for name, content in files.items():

        Path(name).write_text(
            content,
            encoding="utf-8",
        )

        print(
            f"Saved local: {name}"
        )


# ==================================================
# UPDATE GITHUB GIST
# ==================================================

def update_gist(
    files: dict[str, str],
) -> dict[str, Any]:

    if not GITHUB_TOKEN:
        raise RuntimeError(
            "GIST_TOKEN is not set"
        )

    if not GIST_ID:
        raise RuntimeError(
            "GIST_ID is not set"
        )

    payload = {
        "files": {
            name: {
                "content": content,
            }
            for name, content in files.items()
        }
    }

    raw = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        data=raw,
        method="PATCH",
        headers={
            "Accept": (
                "application/vnd.github+json"
            ),
            "Authorization": (
                f"Bearer {GITHUB_TOKEN}"
            ),
            "X-GitHub-Api-Version": (
                "2022-11-28"
            ),
            "User-Agent": (
                "nexthour-gist-updater"
            ),
            "Content-Type": (
                "application/json"
            ),
        },
    )

    try:

        with urllib.request.urlopen(
            req,
            timeout=30,
        ) as r:

            response = json.loads(
                r.read()
            )

        print(
            "Gist updated successfully"
        )

        print(
            "Gist:",
            response.get("html_url"),
        )

        return response

    except urllib.error.HTTPError as e:

        body = e.read().decode(
            "utf-8",
            "replace",
        )

        raise RuntimeError(
            f"GitHub Gist update failed: "
            f"HTTP {e.code}: {body}"
        ) from e


# ==================================================
# MAIN
# ==================================================

def main() -> None:

    print("=" * 50)
    print("NEXTHOUR GIST UPDATER")
    print("=" * 50)

    print(
        "Device ID:",
        Client().device_id,
    )

    # ----------------------------------------------
    # Fetch
    # ----------------------------------------------

    configs = fetch_configs()

    if not configs:

        raise RuntimeError(
            "No configs received. "
            "Gist was NOT updated."
        )

    print(
        f"\nTotal configs: {len(configs)}"
    )

    # ----------------------------------------------
    # Build files
    # ----------------------------------------------

    files = build_files(configs)

    # ----------------------------------------------
    # Save local
    # ----------------------------------------------

    save_local_files(files)

    # ----------------------------------------------
    # Update Gist
    # ----------------------------------------------

    update_gist(files)

    print("\nDone.")


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print("\nInterrupted.")

        sys.exit(130)

    except Exception as e:

        print(
            f"\nERROR: {e}",
            file=sys.stderr,
        )

        sys.exit(1)
