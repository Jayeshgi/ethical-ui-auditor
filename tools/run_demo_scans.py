"""Run read-only API scans and save reproducible demo evidence."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URLS = ("https://example.com", "https://www.booking.com", "https://www.etsy.com")


def scan(api_base: str, url: str, token: str) -> dict:
    payload = json.dumps({"url": url, "max_pages": 1, "scroll_steps": 1}).encode("utf-8")
    request = Request(
        f"{api_base.rstrip('/')}/api/v1/scans",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            job = json.loads(response.read().decode("utf-8"))
            accepted_status = response.status
        status_url = f"{api_base.rstrip('/')}/api/v1/scans/{job['scan_id']}"
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            with urlopen(status_url, timeout=15) as response:
                job = json.loads(response.read().decode("utf-8"))
            if job["status"] == "completed":
                return {"requested_url": url, "http_status": accepted_status, "job": job, "response": job["result"]}
            if job["status"] == "failed":
                return {"requested_url": url, "http_status": accepted_status, "job": job, "error": job.get("error")}
            time.sleep(0.5)
        return {"requested_url": url, "http_status": accepted_status, "job": job, "error": "Scan polling timed out."}
    except HTTPError as error:
        return {"requested_url": url, "http_status": error.code, "error": error.read().decode("utf-8", errors="replace")}
    except URLError as error:
        return {"requested_url": url, "error": str(error.reason)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", default=DEFAULT_URLS)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("AUDITOR_API_TOKEN"), help="Bearer token from /api/v1/auth/login.")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "runtime_data" / "demo_scans.json")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("Provide --token or set AUDITOR_API_TOKEN after logging in.")

    scans = [scan(args.api_base, url, args.token) for url in args.urls]
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scan_mode": "read-only; one page per URL; no form submission or authentication",
        "scans": scans,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    for item in scans:
        response = item.get("response", {})
        findings = sum(len(page.get("findings", [])) for page in response.get("pages", []))
        print(f"{item['requested_url']}: {item.get('http_status', 'error')}; findings={findings}")


if __name__ == "__main__":
    main()
