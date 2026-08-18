#!/usr/bin/env python3
"""Create or update Oklahoma State Agent Builder tools and agents."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from es_config import ROOT

load_dotenv(ROOT / ".env")

SPEC_PATH = ROOT / "kibana" / "okstate-agent-builder.json"
API_VERSION = "2023-10-31"


def kibana_request(method: str, path: str, body: dict | None = None, allow_404: bool = False) -> dict | None:
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
        if allow_404 and exc.code == 404:
            return None
        raise SystemExit(f"Kibana API {method} {path} failed ({exc.code}): {detail}") from exc


def upsert_tool(tool: dict) -> str:
    tool_id = tool["id"]
    existing = kibana_request("GET", f"/api/agent_builder/tools/{tool_id}", allow_404=True)
    if existing is None:
        kibana_request("POST", "/api/agent_builder/tools", tool)
        return "created"
    kibana_request(
        "PUT",
        f"/api/agent_builder/tools/{tool_id}",
        {
            "description": tool["description"],
            "configuration": tool["configuration"],
            "tags": tool.get("tags", []),
        },
    )
    return "updated"


def upsert_agent(agent: dict) -> str:
    agent_id = agent["id"]
    existing = kibana_request("GET", f"/api/agent_builder/agents/{agent_id}", allow_404=True)
    if existing is None:
        kibana_request("POST", "/api/agent_builder/agents", agent)
        return "created"
    payload = {
        "description": agent["description"],
        "configuration": agent["configuration"],
    }
    if "labels" in agent:
        payload["labels"] = agent["labels"]
    kibana_request("PUT", f"/api/agent_builder/agents/{agent_id}", payload)
    return "updated"


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    kibana_url = os.environ["KIBANA_URL"].rstrip("/")

    print("=== Tools ===")
    for tool in spec["tools"]:
        action = upsert_tool(tool)
        print(f"  {action:8} {tool['id']}")

    print("\n=== Agents ===")
    for agent in spec["agents"]:
        action = upsert_agent(agent)
        print(f"  {action:8} {agent['id']}  ({agent['name']})")
        print(f"           {kibana_url}/app/agent_builder/agents/{agent['id']}")

    print("\nOklahoma State Agent Builder assistants ready.")


if __name__ == "__main__":
    main()
