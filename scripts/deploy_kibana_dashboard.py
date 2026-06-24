#!/usr/bin/env python3
"""Deploy Kibana dashboards via the Dashboards API."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_VERSION = "2023-10-31"


def kibana_request(method: str, path: str, body: dict | None = None) -> dict:
    url = os.environ.get("KIBANA_URL", "").rstrip("/") + path
    api_key = os.environ.get("KIBANA_API_KEY") or os.environ.get("ELASTICSEARCH_API_KEY")
    if not url or not api_key:
        raise SystemExit("Set KIBANA_URL and ELASTICSEARCH_API_KEY in .env")

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"ApiKey {api_key}",
            "Content-Type": "application/json",
            "kbn-xsrf": "true",
            "Elastic-Api-Version": API_VERSION,
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise SystemExit(f"Kibana API {method} {path} failed ({exc.code}): {detail}") from exc


def deploy_dashboard(spec_path: Path, dashboard_id: str | None = None) -> str:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if dashboard_id:
        result = kibana_request("PUT", f"/api/dashboards/{dashboard_id}", spec)
    else:
        result = kibana_request("POST", "/api/dashboards", spec)
    dash_id = result.get("id") or dashboard_id
    title = result.get("data", {}).get("title") or spec.get("title")
    kibana_url = os.environ["KIBANA_URL"].rstrip("/")
    print(f"✓ Dashboard deployed: {title}")
    print(f"  ID: {dash_id}")
    print(f"  URL: {kibana_url}/app/dashboards#/view/{dash_id}")
    return dash_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Kibana dashboard JSON")
    parser.add_argument(
        "spec",
        type=Path,
        nargs="?",
        default=ROOT / "kibana" / "at-risk-engagement-dashboard.json",
    )
    parser.add_argument(
        "--id",
        default="booster-at-risk-engagement",
        help="Dashboard ID for upsert (PUT)",
    )
    args = parser.parse_args()
    deploy_dashboard(args.spec, args.id)


if __name__ == "__main__":
    main()
