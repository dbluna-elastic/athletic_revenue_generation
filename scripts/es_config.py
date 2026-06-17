"""Shared Elasticsearch client configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

INDEX_NAME = os.getenv("INDEX_NAME", "athletic-boosters")


def get_client() -> Elasticsearch:
    url = os.environ.get("ELASTICSEARCH_URL")
    if not url:
        raise SystemExit(
            "ELASTICSEARCH_URL is not set. Copy .env.example to .env and configure your cluster."
        )

    api_key = os.environ.get("ELASTICSEARCH_API_KEY")
    username = os.environ.get("ELASTICSEARCH_USERNAME")
    password = os.environ.get("ELASTICSEARCH_PASSWORD")

    if api_key:
        return Elasticsearch(url, api_key=api_key, request_timeout=300)
    if username and password:
        return Elasticsearch(url, basic_auth=(username, password), request_timeout=300)
    raise SystemExit(
        "Set ELASTICSEARCH_API_KEY or ELASTICSEARCH_USERNAME/PASSWORD in .env"
    )
