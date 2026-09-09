"""Synchronize EXCP powerplay data from EliteHub Vault with Google Sheets."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests


VAULT_URL = os.getenv("VAULT_URL", "https://vault.elitehub.eu/graphql")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")
APPS_SCRIPT_TOKEN = os.getenv("APPS_SCRIPT_TOKEN", "")
PROJECT_REPOSITORY_URL = os.getenv("PROJECT_REPOSITORY_URL", "")

EXCP_FACTION_ID = os.getenv(
    "EXCP_FACTION_ID", "35b7ec6b-9465-4c62-bc5b-110ee790967a"
)
MAHON_POWER_ID = os.getenv(
    "MAHON_POWER_ID", "ce1142ad-61e6-4115-b458-b1ddeadada81"
)
MAHON_POWER_NAME = os.getenv("MAHON_POWER_NAME", "Edmund Mahon")

BATCH_SIZE = int(os.getenv("VAULT_BATCH_SIZE", "50"))
MIN_BATCH_SIZE = int(os.getenv("VAULT_MIN_BATCH_SIZE", "10"))
MAX_RETRIES = int(os.getenv("VAULT_MAX_RETRIES", "5"))
REQUEST_DELAY = float(os.getenv("VAULT_REQUEST_DELAY", "1.5"))
VAULT_TIMEOUT = float(os.getenv("VAULT_TIMEOUT", "60"))
MIN_EXCP_SYSTEMS = int(os.getenv("MIN_EXCP_SYSTEMS", "150"))
MIN_MATCH_SYSTEMS = int(os.getenv("MIN_MATCH_SYSTEMS", "1"))

EXCP_SHEET = os.getenv("EXCP_SHEET", "EXCP")
MATCH_SHEET = os.getenv("MATCH_SHEET", "EXCP_Mahon")


EXCP_POWERPLAY_QUERY = """
query ExcpPowerplay(
  $first: Int!
  $offset: Int!
  $factionId: UUID!
  $powerId: UUID!
) {
  systems(
    first: $first
    offset: $offset
    condition: { controllingFactionId: $factionId }
  ) {
    totalCount
    nodes {
      name
      powerplayState
      powerplayStateControlProgress
      powerplayStateReinforcement
      powerplayStateUndermining
      updatedAt
      systemPowerplayPowers(condition: { powerId: $powerId }) {
        totalCount
      }
      powerplayConflicts {
        totalCount
        nodes {
          conflictProgress
          updatedAt
          power { name }
        }
      }
    }
  }
}
"""


class VaultQueryCostError(RuntimeError):
    """Raised when Vault rejects a GraphQL query because it is too expensive."""


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("︎", "").replace("", "").split()).strip()


def format_number(value: Any) -> Any:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return ""
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return value


def format_progress(value: Any) -> float | int | str:
    """Return Vault's 0..1 value as a number for Google Sheets percentage cells."""

    if value is None or value == "":
        return ""
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return ""
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return ""


def parse_vault_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def format_relative_time(value: Any) -> str:
    parsed = parse_vault_datetime(value)
    if parsed is None:
        return ""

    seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    units = (
        (365 * 86400, "year"),
        (30 * 86400, "month"),
        (7 * 86400, "week"),
        (86400, "day"),
        (3600, "hour"),
        (60, "min"),
    )
    if seconds < 60:
        return "just now"
    for divisor, label in units:
        if seconds >= divisor:
            count = seconds // divisor
            suffix = "" if count == 1 or label == "min" else "s"
            return f"{count} {label}{suffix} ago"
    return "just now"


def now_rome_string() -> str:
    return datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M")


def user_agent() -> str:
    base = "Elite-Vault-Powerplay-Sheets-Updater/2.0"
    return f"{base} (+{PROJECT_REPOSITORY_URL})" if PROJECT_REPOSITORY_URL else base


def is_query_cost_message(message: str) -> bool:
    lowered = message.lower()
    return "query cost" in lowered or "cost limit" in lowered


def vault_post(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                VAULT_URL,
                json={"query": query, "variables": variables},
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": user_agent(),
                },
                timeout=VAULT_TIMEOUT,
            )

            if response.status_code == 429:
                try:
                    wait = max(1.0, float(response.headers.get("Retry-After", "")))
                except ValueError:
                    wait = 5.0 * attempt
                print(f"[Vault] Rate limit; retry in {wait:.1f}s")
                time.sleep(wait)
                continue

            response.raise_for_status()
            result = response.json()
            errors = result.get("errors") or []
            if errors:
                message = "; ".join(str(error.get("message", error)) for error in errors)
                if is_query_cost_message(message):
                    raise VaultQueryCostError(message)
                raise RuntimeError(f"GraphQL errors: {message}")
            if result.get("data") is None:
                raise RuntimeError("Vault response does not contain data")
            return result["data"]
        except VaultQueryCostError:
            raise
        except Exception as exc:
            last_error = exc
            print(f"[Vault] Attempt {attempt}/{MAX_RETRIES} failed: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)

    raise RuntimeError("EliteHub Vault is unavailable") from last_error


def fetch_excp_powerplay() -> list[dict[str, Any]]:
    """Fetch only EXCP-controlled systems and their Mahon powerplay relations."""

    offset = 0
    batch_size = BATCH_SIZE
    total_count: int | None = None
    systems: list[dict[str, Any]] = []

    print("\n[Vault] Fetching EXCP controlled systems with powerplay data")
    while total_count is None or offset < total_count:
        variables = {
            "first": batch_size,
            "offset": offset,
            "factionId": EXCP_FACTION_ID,
            "powerId": MAHON_POWER_ID,
        }
        try:
            data = vault_post(EXCP_POWERPLAY_QUERY, variables)
        except VaultQueryCostError:
            if batch_size <= MIN_BATCH_SIZE:
                raise
            new_batch_size = max(MIN_BATCH_SIZE, batch_size // 2)
            print(
                f"[Vault] Query cost too high; batch {batch_size} -> {new_batch_size}"
            )
            batch_size = new_batch_size
            continue

        connection = data.get("systems")
        if not isinstance(connection, dict):
            raise RuntimeError("Vault response is missing the systems connection")

        if total_count is None:
            total_count = int(connection.get("totalCount") or 0)
            print(f"[Vault] Expected EXCP systems: {total_count}")

        nodes = connection.get("nodes") or []
        if not nodes:
            if offset < total_count:
                raise RuntimeError(f"Empty Vault page before completion: {offset}/{total_count}")
            break

        systems.extend(node for node in nodes if isinstance(node, dict))
        offset += len(nodes)
        print(f"[Vault] {min(offset, total_count)}/{total_count} | batch {batch_size}")
        if offset < total_count:
            time.sleep(REQUEST_DELAY)

    unique: dict[str, dict[str, Any]] = {}
    for system in systems:
        name = clean_text(system.get("name"))
        if name:
            system["name"] = name
            unique[name.lower()] = system

    result = sorted(unique.values(), key=lambda item: item["name"].lower())
    if len(result) < MIN_EXCP_SYSTEMS:
        raise RuntimeError(f"Suspicious EXCP dataset: only {len(result)} systems")
    return result


def find_mahon_conflict(system: dict[str, Any]) -> dict[str, Any] | None:
    conflicts = (system.get("powerplayConflicts") or {}).get("nodes") or []
    for conflict in conflicts:
        power = (conflict or {}).get("power") or {}
        if power.get("name") == MAHON_POWER_NAME:
            return conflict
    return None


def build_mahon_row(system: dict[str, Any]) -> list[Any] | None:
    """Build an EXCP_Mahon row, or return None when Mahon is unrelated."""

    relation = system.get("systemPowerplayPowers") or {}
    if int(relation.get("totalCount") or 0) == 0:
        return None

    name = clean_text(system.get("name"))
    state = system.get("powerplayState")
    if not name:
        return None

    if state in {"Exploited", "Fortified", "Stronghold"}:
        return [
            name,
            state,
            format_number(system.get("powerplayStateUndermining")),
            format_number(system.get("powerplayStateReinforcement")),
            format_progress(system.get("powerplayStateControlProgress")),
            format_relative_time(system.get("updatedAt")),
        ]

    if state == "Unoccupied":
        conflict = find_mahon_conflict(system)
        if conflict is None:
            print(f"[Warning] {name}: Mahon relation present but conflict missing")
            return None
        total_conflicts = int(
            (system.get("powerplayConflicts") or {}).get("totalCount") or 0
        )
        return [
            name,
            "Expansion" if total_conflicts == 1 else "Contested",
            "",
            "",
            format_progress(conflict.get("conflictProgress")),
            format_relative_time(conflict.get("updatedAt") or system.get("updatedAt")),
        ]

    print(f"[Warning] {name}: unsupported powerplay state {state!r}")
    return None


def build_excp_values(systems: list[dict[str, Any]]) -> list[list[Any]]:
    timestamp = now_rome_string()
    values: list[list[Any]] = [
        ["Star system", "", "Controlled Systems", "Last Update"]
    ]
    for index, system in enumerate(sorted(systems, key=lambda item: item["name"].lower())):
        values.append(
            [
                system["name"],
                "",
                len(systems) if index == 0 else "",
                timestamp if index == 0 else "",
            ]
        )
    return values


def build_excp_mahon_values(
    systems: list[dict[str, Any]],
) -> tuple[list[list[Any]], list[list[Any]]]:
    rows = [row for system in systems if (row := build_mahon_row(system)) is not None]
    rows.sort(key=lambda row: row[0].lower())
    timestamp = now_rome_string()
    values: list[list[Any]] = [
        [
            "Star system",
            "State",
            "Under",
            "Reinf",
            "Progress",
            "Updated",
            "",
            "Systems",
            "Last Update",
        ]
    ]
    for index, row in enumerate(rows):
        values.append(
            row
            + [""]
            + [len(rows) if index == 0 else "", timestamp if index == 0 else ""]
        )
    return values, rows


def post_apps_script(sheet: str, values: list[list[Any]]) -> None:
    if not APPS_SCRIPT_URL:
        raise RuntimeError("APPS_SCRIPT_URL is required unless --dry-run is used")

    payload = {
        "action": "write",
        "sheet": sheet,
        "values": values,
    }
    if APPS_SCRIPT_TOKEN:
        payload["token"] = APPS_SCRIPT_TOKEN

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                APPS_SCRIPT_URL,
                json=payload,
                timeout=90,
            )
            response.raise_for_status()
            try:
                result = response.json()
            except requests.exceptions.JSONDecodeError as exc:
                raise RuntimeError("Apps Script returned a non-JSON response") from exc
            if result.get("status") != "ok":
                raise RuntimeError(f"Apps Script error: {json.dumps(result)}")
            print(f"[Sheets] {sheet}: {len(values) - 1} rows written")
            return
        except Exception as exc:
            last_error = exc
            print(f"[Apps Script] Attempt {attempt}/3 failed for {sheet}: {exc}")
            if attempt < 3:
                time.sleep(5 * attempt)
    raise RuntimeError(f"Apps Script is unavailable for {sheet}") from last_error


def print_summary(excp_count: int, mahon_rows: list[list[Any]]) -> None:
    states: dict[str, int] = {}
    for row in mahon_rows:
        states[row[1]] = states.get(row[1], 0) + 1

    print(f"\nEXCP controlled: {excp_count}")
    print(f"EXCP_Mahon: {len(mahon_rows)}")
    for state in ("Stronghold", "Fortified", "Exploited", "Expansion", "Contested"):
        print(f"  {state}: {states.get(state, 0)}")


def run(dry_run: bool = False) -> dict[str, int]:
    started = time.time()
    systems = fetch_excp_powerplay()
    excp_values = build_excp_values(systems)
    match_values, mahon_rows = build_excp_mahon_values(systems)

    if len(mahon_rows) < MIN_MATCH_SYSTEMS:
        raise RuntimeError(
            f"Suspicious EXCP_Mahon dataset: only {len(mahon_rows)} systems"
        )

    if not dry_run:
        post_apps_script(EXCP_SHEET, excp_values)
        post_apps_script(MATCH_SHEET, match_values)

    print_summary(len(systems), mahon_rows)
    print(f"Completed in {time.time() - started:.1f}s")
    if dry_run:
        print("Dry run: no Google Sheet was modified")
    return {"excp": len(systems), "matches": len(mahon_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and validate Vault data without writing to Google Sheets",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
