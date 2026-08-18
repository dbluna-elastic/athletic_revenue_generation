#!/usr/bin/env python3
"""Create and start gameday-stand-revenue ML anomaly detector."""

from __future__ import annotations

import argparse
import time

from es_config import get_client
from demo_profile import add_profile_argument, load_profile


def job_exists(client, job_id: str) -> bool:
    try:
        client.ml.get_jobs(job_id=job_id)
        return True
    except Exception:
        return False


def create_job(client, job_id: str, pos_index: str) -> None:
    print(f"Creating ML job: {job_id}")
    client.ml.put_job(
        job_id=job_id,
        body={
            "description": (
                "Detects abnormal transaction rate drops at individual concession stands"
            ),
            "analysis_config": {
                "bucket_span": "2m",
                "detectors": [
                    {
                        "function": "low_count",
                        "over_field_name": "stand_id",
                        "detector_description": (
                            "Unusually low transaction count per stand per 2-minute window"
                        ),
                    },
                    {
                        "function": "low_sum",
                        "field_name": "total_amount",
                        "over_field_name": "stand_id",
                        "detector_description": (
                            "Unusually low revenue per stand per 2-minute window"
                        ),
                    },
                ],
                "influencers": ["stand_id", "stand_zone"],
            },
            "data_description": {"time_field": "transaction_time"},
            "datafeed_config": {
                "indices": [pos_index],
                "query": {"match_all": {}},
            },
        },
    )
    print(f"✓ Job {job_id} created")


def start_datafeed(client, job_id: str, datafeed_id: str) -> None:
    try:
        client.ml.open_job(job_id=job_id)
    except Exception:
        pass
    stats = client.ml.get_datafeed_stats(datafeed_id=datafeed_id)
    state = stats["datafeeds"][0]["state"]
    if state == "started":
        print(f"Datafeed {datafeed_id} already running")
        return
    client.ml.start_datafeed(datafeed_id=datafeed_id, start="0")
    print(f"✓ Datafeed {datafeed_id} started")


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup ML anomaly job for POS stands")
    add_profile_argument(parser)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--start", action="store_true", help="Open job and start datafeed")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    job_id = profile.job_id("gameday-stand-revenue")
    datafeed_id = job_id
    pos_index = profile.index("square-pos-transactions")

    client = get_client()
    if client.count(index=pos_index)["count"] == 0:
        raise SystemExit(f"{pos_index} is empty. Run seed first.")

    if args.recreate and job_exists(client, job_id):
        try:
            client.ml.stop_datafeed(datafeed_id=datafeed_id)
        except Exception:
            pass
        try:
            client.ml.close_job(job_id=job_id)
        except Exception:
            pass
        try:
            client.ml.delete_job(job_id=job_id, force=True)
        except Exception:
            pass
        print(f"Removed existing job {job_id}")
        time.sleep(2)

    if not job_exists(client, job_id):
        create_job(client, job_id, pos_index)

    if args.start or args.recreate:
        start_datafeed(client, job_id, datafeed_id)

    stats = client.ml.get_job_stats(job_id=job_id)
    job = stats["jobs"][0]
    print(
        f"Job state: {job['state']} | "
        f"processed records: {job['data_counts'].get('processed_record_count', 0)}"
    )


if __name__ == "__main__":
    main()
