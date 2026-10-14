"""Standalone API smoke test; writes a unique demo account and its interactions."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4
from pathlib import Path
import httpx


def run_smoke(client: httpx.Client, prefix: str = "/api/v1") -> dict:
    checks = []

    def request(method, path, *, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code != expected:
            raise RuntimeError(
                f"{method} {path}: expected {expected}, got {response.status_code}: {response.text[:200]}"
            )
        checks.append(f"{method} {path}: {expected}")
        return response.json() if response.content else None

    request("GET", "/livez")
    request("GET", "/readyz")
    schema = request("GET", "/openapi.json")
    if any("/chat" in p or "/knowledge" in p for p in schema["paths"]):
        raise RuntimeError("Agent endpoints unexpectedly exposed")
    listing = request("GET", f"{prefix}/recipes", params={"limit": 2})
    if not listing["items"]:
        raise RuntimeError("Seed recipes are required for the smoke test")
    recipe_id = listing["items"][0]["id"]
    request("GET", f"{prefix}/recipes/{recipe_id}")
    request("PUT", f"{prefix}/recipes/{recipe_id}/like", expected=401)
    email = f"smoke-{uuid4().hex}@example.test"
    credentials = {"email": email, "password": "SafeMealDemo12345"}
    tokens = request("POST", f"{prefix}/auth/register", expected=201, json=credentials)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    request("GET", f"{prefix}/auth/me", headers=headers)
    for _ in range(2):
        liked = request("PUT", f"{prefix}/recipes/{recipe_id}/like", headers=headers)
        if not liked["liked"]:
            raise RuntimeError("Like state was not persisted")
    request("PUT", f"{prefix}/recipes/{recipe_id}/favorite", headers=headers)
    favorites = request("GET", f"{prefix}/recipes/favorites", headers=headers)
    if len(favorites["items"]) != 1:
        raise RuntimeError("Favorite list did not contain the demo recipe")
    request(
        "POST",
        f"{prefix}/recipes/interactions/query",
        headers=headers,
        json={"recipe_ids": [recipe_id]},
    )
    request("PUT", f"{prefix}/recipes/{recipe_id}/view", headers=headers)
    history = request("GET", f"{prefix}/recipes/history", headers=headers)
    if len(history["items"]) != 1:
        raise RuntimeError("View history was not persisted")
    request("GET", f"{prefix}/recipes/rankings", headers=headers)
    request("DELETE", f"{prefix}/recipes/{recipe_id}/like", headers=headers)
    request("DELETE", f"{prefix}/recipes/{recipe_id}/favorite", headers=headers)
    refreshed = request(
        "POST",
        f"{prefix}/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    request(
        "POST",
        f"{prefix}/auth/logout",
        expected=204,
        json={"refresh_token": refreshed["refresh_token"]},
    )
    request("POST", f"{prefix}/auth/login", json=credentials)
    return {
        "status": "passed",
        "checks": checks,
        "account": email,
        "recipe_id": recipe_id,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--prefix", default="/api/v1")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=15) as client:
        result = run_smoke(client, args.prefix)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
