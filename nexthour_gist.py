
#!/usr/bin/env python3
"""Fetch Nexthour V2Ray configs and update a GitHub Gist."""

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


# --------------------------------------------------
# Nexthour
# --------------------------------------------------

BASE = "https://api.nexthour.app"

API_KEY = os.environ["NEXTHOUR_API_KEY"]
PKG = os.environ.get(
    "NEXTHOUR_PACKAGE",
    "com.gamenetvpn.pingbooster",
)
CERT = os.environ["NEXTHOUR_CERT"]
KEY = bytes.fromhex(os.environ["NEXTHOUR_HMAC_KEY"])

EMPTY_SHA = hashlib.sha256(b"").hexdigest()


# --------------------------------------------------
# GitHub Gist
# --------------------------------------------------

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GIST_ID = os.environ["GIST_ID"]

GIST_LINKS = "nexthour_v2ray_links.txt"
GIST_JSON = "nexthour_v2ray_configs.json"

# Optional: also save files in the repository.
SAVE_LOCAL = os.environ.get("SAVE_LOCAL", "false").lower() == "true"


class Client:
    def __init__(self) -> None:
        self.device_id = "android-" + uuid.uuid4().hex[:16]
        self.session_token: str | None = None

    def _ts(self) -> str:
        """
        Ask Nexthour for server time.

        Falls back to local Unix time if the endpoint
        does not return x-server-time.
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
            with urllib.request.urlopen(req, timeout=10) as r:
                server_time = r.headers.get("x-server-time")
                if server_time:
                    return str(server_time)

        except urllib.error.HTTPError as e:
            server_time = e.headers.get("x-server-time")
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

        if body is None:
            raw = None
            body_sha = EMPTY_SHA
        else:
            raw = json.dumps(
                body,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")

            body_sha = hashlib.sha256(raw).hexdigest()

        timestamp = self._ts()

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
            headers["X-Session-Token"] = self.session_token

        if raw is not None:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            f"{BASE}{path}",
            data=raw,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()

                try:
                    data = json.loads(data)
                except Exception:
                    data = data.decode("utf-8", "replace")

                return r.status, data

        except urllib.error.HTTPError as e:
            data = e.read()

            try:
                data = json.loads(data)
            except Exception:
                data = data.decode("utf-8", "replace")

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

        if code == 200 and isinstance(data, dict):
            self.session_token = data.get("session_token")

        return code, data


def fetch_configs() -> list[dict[str, Any]]:
    client = Client()

    code, registration = client.register()

    print(f"register: {code}")

    if code != 200:
        print("Registration response:", registration)

    code, servers = client.request("GET", "/api/servers")

    if code != 200 or not isinstance(servers, dict):
        raise RuntimeError(
            f"Failed to fetch servers: HTTP {code}: {servers}"
        )

    items = servers.get("items") or []

    v2ray_servers = [
        s for s in items
        if isinstance(s, dict)
        and (s.get("protocol") or "").lower() == "v2ray"
    ]

    print(f"V2Ray servers: {len(v2ray_servers)}")

    all_configs: list[dict[str, Any]] = []

    for server in v2ray_servers:
        sid = server.get("id")

        if not sid:
            continue

        code, data = client.request(
            "GET",
            f"/api/servers/{sid}/config",
        )

        if code != 200 or not isinstance(data, dict):
            print(f"FAIL {sid}: {code} {data}")
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
                "sub_protocol": data.get("sub_protocol"),
                "config_id": cfg.get("id"),
                "url": url,
            }

            all_configs.append(entry)

            print(
                f"  {server.get('country')}/"
                f"{server.get('location')}: "
                f"{url[:80]}..."
            )

    return all_configs


def build_files(
    configs: list[dict[str, Any]],
) -> dict[str, str]:

    fetched_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(),
    )

    result = {
        "fetched_at": fetched_at,
        "count": len(configs),
        "configs": configs,
    }

    json_text = json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    txt_lines: list[str] = []

    for entry in configs:
        country = entry.get("country") or ""
        location = entry.get("location") or ""
        tier = entry.get("tier") or ""

        txt_lines.append(
            f"# {country}/{location} tier={tier}"
        )
        txt_lines.append(entry["url"])
        txt_lines.append("")

    txt_text = "\n".join(txt_lines)

    if txt_text and not txt_text.endswith("\n"):
        txt_text += "\n"

    return {
        GIST_JSON: json_text,
        GIST_LINKS: txt_text,
    }


def update_gist(files: dict[str, str]) -> dict[str, Any]:
    """
    Update existing Gist using GitHub API.
    """

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
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nexthour-gist-updater",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            response = json.loads(r.read())

        print("Gist updated successfully")
        print("Gist:", response.get("html_url"))

        return response

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")

        raise RuntimeError(
            f"GitHub Gist update failed: HTTP {e.code}: {body}"
        ) from e


def main() -> None:
    print("Starting Nexthour updater...")

    configs = fetch_configs()

    if not configs:
        raise RuntimeError(
            "No configs received. Gist was NOT updated."
        )

    files = build_files(configs)

    if SAVE_LOCAL:
        Path(GIST_JSON).write_text(
            files[GIST_JSON],
            encoding="utf-8",
        )

        Path(GIST_LINKS).write_text(
            files[GIST_LINKS],
            encoding="utf-8",
        )

        print("Local files saved.")

    update_gist(files)

    print(f"Saved {len(configs)} configs.")
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
