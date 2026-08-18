#!/usr/bin/env python3
"""Create and execute section-to-fan-tier enrich policy."""

from __future__ import annotations

import argparse
import time

from es_config import get_client
from demo_profile import add_profile_argument, load_profile


def delete_policy(client, policy_name: str) -> None:
    try:
        client.enrich.delete_policy(name=policy_name)
        print(f"Deleted policy {policy_name}")
        time.sleep(2)
    except Exception:
        pass


def put_policy(client, policy_name: str, source_index: str) -> None:
    print(f"Creating enrich policy: {policy_name}")
    client.enrich.put_policy(
        name=policy_name,
        body={
            "match": {
                "indices": source_index,
                "match_field": "section",
                "enrich_fields": ["fan_tier", "ticket_type"],
            }
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup fan tier enrich policy")
    add_profile_argument(parser)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    policy_name = profile.policy_name("section-to-fan-tier")
    source_index = profile.index("paciolan-ticket-events")

    client = get_client()
    count = client.count(index=source_index)["count"]
    if count == 0:
        raise SystemExit(
            f"{source_index} is empty. Run: python scripts/gameday_replay.py seed --profile {profile.id if profile.index_prefix else 'default'}"
        )

    exists = False
    try:
        client.enrich.get_policy(name=policy_name)
        exists = True
    except Exception:
        pass

    if args.recreate and exists:
        delete_policy(client, policy_name)
        exists = False

    if not exists:
        put_policy(client, policy_name, source_index)

    print("Executing policy...")
    try:
        client.enrich.execute_policy(name=policy_name)
    except Exception as exc:
        print(f"Execute failed ({exc}), recreating policy...")
        delete_policy(client, policy_name)
        put_policy(client, policy_name, source_index)
        client.enrich.execute_policy(name=policy_name)

    print(f"✓ Enrich policy {policy_name} ready")


if __name__ == "__main__":
    main()
