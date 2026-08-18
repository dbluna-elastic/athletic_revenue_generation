#!/usr/bin/env python3
"""Deploy all gameday revenue Kibana dashboards."""

from __future__ import annotations

import argparse
from pathlib import Path

from deploy_kibana_dashboard import deploy_dashboard
from es_config import ROOT
from demo_profile import add_profile_argument, load_profile

DASHBOARDS = [
    ("gameday-revenue-overview", ROOT / "kibana" / "gameday-revenue-overview-dashboard.json"),
    ("gameday-fan-segments", ROOT / "kibana" / "gameday-fan-segments-dashboard.json"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy gameday Kibana dashboards")
    add_profile_argument(parser)
    args = parser.parse_args()
    profile = load_profile(args.profile)
    for dash_id, spec_path in DASHBOARDS:
        deploy_dashboard(spec_path, dash_id, profile=profile)
    print("\nAll gameday dashboards deployed.")


if __name__ == "__main__":
    main()
