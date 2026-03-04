"""
Health check script for Smart Goblin bot container.

Verifies connectivity to Telegram Bot API by calling getMe endpoint.
Exit code 0 = healthy, 1 = unhealthy.
"""

import os
import sys
import urllib.request
import urllib.error


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set")
        return 1

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print("OK")
                return 0
            print(f"Unexpected status: {resp.status}")
            return 1
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"Health check failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
