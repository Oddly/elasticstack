#!/usr/bin/env python3
"""Check the collection's supported dependency versions for end-of-life."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEPENDENCIES = (
    ("rocky-linux", "9", "Rocky Linux 9"),
    ("rocky-linux", "10", "Rocky Linux 10"),
    ("debian", "13", "Debian 13 (Trixie)"),
    ("ubuntu", "22.04", "Ubuntu 22.04 (Jammy)"),
    ("ubuntu", "24.04", "Ubuntu 24.04 (Noble)"),
    ("ubuntu", "26.04", "Ubuntu 26.04 (Resolute Raccoon)"),
    ("python", "3.11", "Python 3.11"),
    ("python", "3.12", "Python 3.12"),
    ("python", "3.13", "Python 3.13"),
    ("ansible-core", "2.20", "ansible-core 2.20"),
    ("ansible-core", "2.21", "ansible-core 2.21"),
)
WARNING_DAYS = 180


def classify_eol(label: str, eol: object, today: date) -> dict[str, object]:
    """Classify an end-of-life API value using a deterministic reference date."""
    if eol is True or eol == "true":
        return {
            "level": "eol",
            "message": f"ALERT: {label} is EOL",
            "issue": f"- **{label}** is EOL",
        }

    if eol is False or eol == "false":
        return {
            "level": "supported",
            "message": f"OK: {label} is supported",
            "issue": None,
        }

    if not isinstance(eol, str):
        return {
            "level": "unknown",
            "message": f"WARNING: Could not parse EOL data for {label}: {eol!r}",
            "issue": f"- **{label}** has an unrecognized EOL value ({eol!r})",
        }

    try:
        eol_date = date.fromisoformat(eol[:10])
    except ValueError:
        return {
            "level": "unknown",
            "message": f"WARNING: Could not parse EOL data for {label}: {eol}",
            "issue": f"- **{label}** has an unrecognized EOL value ({eol})",
        }

    days_left = (eol_date - today).days
    if days_left < 0:
        return {
            "level": "eol",
            "message": f"ALERT: {label} is EOL since {eol}",
            "issue": f"- **{label}** is EOL (since {eol})",
        }

    if days_left < WARNING_DAYS:
        return {
            "level": "warning",
            "message": f"WARNING: {label} reaches EOL on {eol} ({days_left} days)",
            "issue": f"- **{label}** reaches EOL on {eol} ({days_left} days)",
        }

    return {
        "level": "supported",
        "message": f"OK: {label} supported until {eol} ({days_left} days)",
        "issue": None,
    }


def write_github_env(path: Path, issues: list[str]) -> None:
    """Write the values consumed by the follow-up GitHub issue step."""
    with path.open("a", encoding="utf-8") as env_file:
        if issues:
            env_file.write("ISSUES<<EOF\n")
            env_file.write("\n".join(issues))
            env_file.write("\nEOF\nHAS_ISSUES=true\n")
        else:
            env_file.write("HAS_ISSUES=false\n")


def _fetch_eol(api: str, product: str, version: str) -> object:
    request = Request(
        f"{api.rstrip('/')}/{product}/{version}.json",
        headers={"Accept": "application/json", "User-Agent": "oddly-elasticstack-eol-check"},
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        return json.load(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="https://endoflife.date/api")
    parser.add_argument(
        "--today",
        help="reference date as YYYY-MM-DD (useful for deterministic checks)",
    )
    parser.add_argument(
        "--github-env",
        type=Path,
        help="append HAS_ISSUES and ISSUES values to a GitHub environment file",
    )
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else date.today()
    issues = []

    for product, version, label in DEPENDENCIES:
        try:
            payload = _fetch_eol(args.api, product, version)
            eol = payload.get("eol") if isinstance(payload, dict) else None
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            print(f"WARNING: Could not fetch EOL data for {label}: {error}")
            continue

        result = classify_eol(label, eol, today)
        print(result["message"])
        if result["issue"]:
            issues.append(str(result["issue"]))

    if args.github_env:
        write_github_env(args.github_env, issues)

    if issues:
        print("::warning::EOL dependencies detected")
    else:
        print("All dependencies are within support window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
