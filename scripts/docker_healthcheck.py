from __future__ import annotations

import sys
from urllib.request import urlopen


def main() -> int:
    urls = (
        "http://127.0.0.1:9889/health",
        "http://127.0.0.1:8000/health",
    )
    for url in urls:
        try:
            with urlopen(url, timeout=5) as response:
                if response.status != 200:
                    print(
                        f"healthcheck failed: {url} returned status {response.status}",
                        file=sys.stderr,
                    )
                    return 1
        except Exception as exc:  # pragma: no cover - exercised by Docker runtime
            print(f"healthcheck failed: {url}: {exc}", file=sys.stderr)
            return 1
        print(f"healthcheck ok: {url}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
