"""University demo profiles: index prefixes, story constants, dashboard titles."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from es_config import ROOT

PROFILES_DIR = ROOT / "profiles"

DEFAULT_GATES = ["Gate A", "Gate B", "Gate C", "Gate D", "Gate E", "Gate F"]

DEFAULT_STANDS = [
    {
        "id": "S01",
        "name": "North Concourse Beer Garden",
        "zone": "North",
        "items": [
            ("Draft Beer", 12.0),
            ("Craft Beer", 14.0),
            ("Wine", 11.0),
            ("Spirits", 13.0),
        ],
    },
    {
        "id": "S02",
        "name": "Main Grill — Gate A",
        "zone": "North",
        "items": [
            ("Hot Dog", 7.0),
            ("Nachos", 9.0),
            ("Soda", 5.0),
            ("Water", 4.0),
            ("Burger", 12.0),
        ],
    },
    {
        "id": "S03",
        "name": "South End Zone Cantina",
        "zone": "South",
        "items": [("Tacos", 11.0), ("Draft Beer", 12.0), ("Soda", 5.0), ("Chips", 6.0)],
    },
    {
        "id": "S04",
        "name": "Premium Club Bar",
        "zone": "Premium",
        "items": [
            ("Craft Beer", 16.0),
            ("Wine", 14.0),
            ("Cocktail", 18.0),
            ("Charcuterie", 22.0),
        ],
    },
    {
        "id": "S05",
        "name": "Student Section Snacks",
        "zone": "Student",
        "items": [("Hot Dog", 6.0), ("Soda", 4.0), ("Popcorn", 5.0), ("Water", 3.0)],
    },
    {
        "id": "S06",
        "name": "West Concourse Grill",
        "zone": "West",
        "items": [("Burger", 12.0), ("Draft Beer", 12.0), ("Fries", 7.0), ("Soda", 5.0)],
    },
    {
        "id": "S07",
        "name": "Team Store — Main",
        "zone": "Main",
        "items": [
            ("Jersey", 120.0),
            ("Hat", 35.0),
            ("Shirt", 45.0),
            ("Hoodie", 75.0),
        ],
    },
    {
        "id": "S08",
        "name": "Team Store — South",
        "zone": "South",
        "items": [("Jersey", 120.0), ("Hat", 35.0), ("Pennant", 18.0), ("Shirt", 45.0)],
    },
    {
        "id": "S09",
        "name": "East End Zone Bar",
        "zone": "East",
        "items": [
            ("Draft Beer", 12.0),
            ("Craft Beer", 14.0),
            ("Spirits", 13.0),
            ("Shot", 9.0),
        ],
    },
    {
        "id": "S10",
        "name": "Visiting Fan Concessions",
        "zone": "Visitor",
        "items": [("Hot Dog", 7.0), ("Soda", 5.0), ("Nachos", 9.0), ("Water", 4.0)],
    },
]

INDEX_SUBSTITUTIONS = [
    "booster-engagement-events",
    "booster-donor-lookup",
    "square-pos-transactions",
    "paciolan-ticket-events",
    "athletic-boosters",
]


@dataclass
class DemoProfile:
    id: str
    display_name: str
    index_prefix: str
    home_state: str
    fund_name: str
    dashboard_title_prefix: str
    demo_query: str
    states: list[str]
    state_weights: list[int]
    game_id: str
    gates: list[str] = field(default_factory=lambda: list(DEFAULT_GATES))
    stands: list[dict] = field(default_factory=lambda: list(DEFAULT_STANDS))

    def index(self, name: str) -> str:
        return f"{self.index_prefix}{name}"

    def job_id(self, name: str) -> str:
        prefix = self.index_prefix.rstrip("-")
        return f"{prefix}-{name}" if prefix else name

    def policy_name(self, name: str) -> str:
        prefix = self.index_prefix.rstrip("-")
        return f"{prefix}-{name}" if prefix else name

    def dashboard_id(self, name: str) -> str:
        prefix = self.index_prefix.rstrip("-")
        return f"{prefix}-{name}" if prefix else name

    def title(self, base: str) -> str:
        if not self.dashboard_title_prefix:
            return base
        if base.startswith(self.dashboard_title_prefix):
            return base
        return f"{self.dashboard_title_prefix} — {base}"


def default_profile() -> DemoProfile:
    return DemoProfile(
        id="default",
        display_name="Athletic Department",
        index_prefix="",
        home_state="TX",
        fund_name="athletics fund",
        dashboard_title_prefix="",
        demo_query="Texas alumni football games real estate holdings",
        states=["TX", "CA", "FL", "NY", "OH", "GA", "NC", "IL"],
        state_weights=[25, 15, 12, 10, 8, 8, 8, 14],
        game_id="GAME-2025-HOME-01",
    )


def _parse_stands(raw: list[dict[str, Any]] | None) -> list[dict]:
    if not raw:
        return list(DEFAULT_STANDS)
    stands = []
    for stand in raw:
        items = stand.get("items") or []
        stands.append(
            {
                "id": stand["id"],
                "name": stand["name"],
                "zone": stand["zone"],
                "items": [tuple(item) for item in items],
            }
        )
    return stands


def load_profile(name: str | None) -> DemoProfile:
    if not name:
        return default_profile()
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"Profile not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DemoProfile(
        id=data["id"],
        display_name=data["display_name"],
        index_prefix=data.get("index_prefix", ""),
        home_state=data["home_state"],
        fund_name=data.get("fund_name", "athletics fund"),
        dashboard_title_prefix=data.get("dashboard_title_prefix", ""),
        demo_query=data.get("demo_query", ""),
        states=list(data["states"]),
        state_weights=list(data["state_weights"]),
        game_id=data.get("game_id", "GAME-2025-HOME-01"),
        gates=list(data.get("gates") or DEFAULT_GATES),
        stands=_parse_stands(data.get("stands")),
    )


def add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        default=os.getenv("DEMO_PROFILE"),
        help="University profile id (e.g. oklahoma-state). Default: unprefixed Texas demo.",
    )


def substitute_indexes(text: str, profile: DemoProfile) -> str:
    if not profile.index_prefix:
        return text
    for name in INDEX_SUBSTITUTIONS:
        text = text.replace(name, profile.index(name))
    return text
