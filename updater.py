"""Synchronize EliteHub Vault data with Google Sheets via Apps Script."""

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

BATCH_SIZE = int(os.getenv("VAULT_BATCH_SIZE", "100"))
MIN_BATCH_SIZE = int(os.getenv("VAULT_MIN_BATCH_SIZE", "10"))
MAX_RETRIES = int(os.getenv("VAULT_MAX_RETRIES", "3"))
REQUEST_DELAY = float(os.getenv("VAULT_REQUEST_DELAY", "1.5"))
MIN_MAHON_SYSTEMS = int(os.getenv("MIN_MAHON_SYSTEMS", "1000"))
MIN_EXCP_SYSTEMS = int(os.getenv("MIN_EXCP_SYSTEMS", "150"))

MAHON_SHEET = os.getenv("MAHON_SHEET", "Mahon")
EXCP_SHEET = os.getenv("EXCP_SHEET", "EXCP")
MATCH_SHEET = os.getenv("MATCH_SHEET", "EXCP_Mahon")


MAHON_QUERY = """
query MahonSystems($first: Int!, $offset: Int!) {
  powerplayPowerByName(name: "Edmund Mahon") {
    systemPowerplayPowersByPowerId(first: $first, offset: $offset) {
      totalCount
      nodes {
        system {
          name
          powerplayState
          powerplayStateControlProgress
          powerplayStateReinforcement
          powerplayStateUndermining
          updatedAt
        }
      }
    }
  }
}
"""

CONFLICT_QUERY = """
query MahonConflicts($first: Int!, $offset: Int!) {
  powerplayPowerByName(name: "Edmund Mahon") {
    powerplayConflictsByPowerId(first: $first, offset: $offset) {
      totalCount
      nodes {
        conflictProgress
        updatedAt
        system {
          name
          powerplayState
          powerplayConflicts { totalCount }
        }
      }
    }
  }
}
"""

EXCP_QUERY = """
query ExcpSystems($first: Int!, $offset: Int!, $factionId: UUID!) {
  systems(
    first: $first
    offset: $offset
    condition: { controllingFactionId: $factionId }
  ) {
    totalCount
    nodes { name }
  }
}
"""


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("︎", "").replace("", "").split()).strip()


def format_number(value: Any) -> Any:
    if value is None:
        return ""
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return ""
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return value


def format_progress(value: Any) -> str:
    if value is None:
        return ""
    try:
        text = f"{float(value) * 100:.2f}".rstrip("0").rstrip(".")
        return f"{text}%"
    except (TypeError, ValueError):
        return ""


def format_relative_time(timestamp_string: str | None) -> str:
    if not timestamp_string:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp_string.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        units = (
            (365 * 86400, "year"),
            (30 * 86400, "month"),
            (7 * 86400, "week"),
            (86400, "day"),
            (3600, "hour"),
            (60, "minute"),
            (1, "second"),
        )
        for divisor, label in units:
            if seconds >= divisor or divisor == 1:
                count = seconds // divisor
                suffix = "" if count == 1 else "s"
                return f"{count} {label}{suffix} ago"
    except (TypeError, ValueError):
        return timestamp_string
    return timestamp_string


def now_rome_string() -> str:
    return datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M")


def is_query_cost_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "query cost" in message or "cost limit" in message


def user_agent() -> str:
    base = "Elite-Vault-Sheets-Updater/1.0"
    return f"{base} (+{PROJECT_REPOSITORY_URL})" if PROJECT_REPOSITORY_URL else base


def vault_post(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = {"query": query, "variables": variables}
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                VAULT_URL,
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": user_agent()},
                timeout=45,
            )
            if response.status_code == 429:
                try:
                    wait = float(response.headers.get("Retry-After", ""))
                except ValueError:
                    wait = 10 * attempt
                print(f"[Vault] Rate limit; retry in {wait:.1f}s")
                time.sleep(wait)
                continue

            response.raise_for_status()
            result = response.json()
            if result.get("errors"):
                raise RuntimeError(
                    "GraphQL errors: "
                    + json.dumps(result["errors"], ensure_ascii=False)
                )
            if result.get("data") is None:
                raise RuntimeError("Vault response does not contain data")
            return result["data"]
        except Exception as exc:
            last_error = exc
            print(f"[Vault] Attempt {attempt}/{MAX_RETRIES} failed: {exc}")
            if is_query_cost_error(exc):
                raise
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)

    raise RuntimeError("EliteHub Vault is unavailable") from last_error


def fetch_connection(
    query: str,
    connection_path: tuple[str, ...],
    extra_variables: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    offset = 0
    total_count: int | None = None
    batch_size = BATCH_SIZE
    collected: list[dict[str, Any]] = []

    while True:
        variables = {"first": batch_size, "offset": offset}
        variables.update(extra_variables or {})
        try:
            data: Any = vault_post(query, variables)
        except RuntimeError as exc:
            if not is_query_cost_error(exc) or batch_size <= MIN_BATCH_SIZE:
                raise
            new_batch = max(MIN_BATCH_SIZE, batch_size // 2)
            print(f"[Vault] Query cost too high; batch {batch_size} -> {new_batch}")
            batch_size = new_batch
            continue

        connection: Any = data
        for key in connection_path:
            if not isinstance(connection, dict) or connection.get(key) is None:
                raise RuntimeError(f"Missing Vault field: {'.'.join(connection_path)}")
            connection = connection[key]

        if total_count is None:
            total_count = int(connection.get("totalCount") or 0)
            print(f"[Vault] Expected records: {total_count}")

        nodes = connection.get("nodes") or []
        if not nodes:
            if offset < total_count:
                raise RuntimeError(f"Empty page before completion: {offset}/{total_count}")
            break

        collected.extend(nodes)
        offset += len(nodes)
        print(f"[Vault] {min(offset, total_count)}/{total_count} | batch {batch_size}")
        if offset >= total_count:
            break
        time.sleep(REQUEST_DELAY)

    return collected


def occupied_row(system: dict[str, Any]) -> list[Any] | None:
    name = clean_text(system.get("name"))
    state = system.get("powerplayState")
    if not name or state not in {"Exploited", "Fortified", "Stronghold"}:
        return None
    return [
        name,
        state,
        format_number(system.get("powerplayStateUndermining")),
        format_number(system.get("powerplayStateReinforcement")),
        format_progress(system.get("powerplayStateControlProgress")),
        format_relative_time(system.get("updatedAt")),
    ]


def conflict_row(conflict: dict[str, Any]) -> list[Any] | None:
    system = conflict.get("system") or {}
    name = clean_text(system.get("name"))
    if not name or system.get("powerplayState") != "Unoccupied":
        return None
    count = int((system.get("powerplayConflicts") or {}).get("totalCount") or 0)
    if count <= 0:
        return None
    return [
        name,
        "Expansion" if count == 1 else "Contested",
        "",
        "",
        format_progress(conflict.get("conflictProgress")),
        format_relative_time(conflict.get("updatedAt")),
    ]


def fetch_powerplay() -> list[list[Any]]:
    print("\n[Vault] Fetching Edmund Mahon occupied systems")
    occupied_nodes = fetch_connection(
        MAHON_QUERY,
        ("powerplayPowerByName", "systemPowerplayPowersByPowerId"),
    )
    print("\n[Vault] Fetching Edmund Mahon conflicts")
    conflict_nodes = fetch_connection(
        CONFLICT_QUERY,
        ("powerplayPowerByName", "powerplayConflictsByPowerId"),
    )

    rows: dict[str, list[Any]] = {}
    for node in conflict_nodes:
        row = conflict_row(node or {})
        if row:
            rows[row[0].lower()] = row
    for node in occupied_nodes:
        row = occupied_row((node or {}).get("system") or {})
        if row:
            rows[row[0].lower()] = row

    result = sorted(rows.values(), key=lambda row: row[0].lower())
    if len(result) < MIN_MAHON_SYSTEMS:
        raise RuntimeError(f"Suspicious Mahon dataset: only {len(result)} systems")
    return result


def fetch_excp() -> list[str]:
    print("\n[Vault] Fetching Expanders Corp controlled systems")
    nodes = fetch_connection(
        EXCP_QUERY,
        ("systems",),
        {"factionId": EXCP_FACTION_ID},
    )
    systems = sorted(
        {clean_text((node or {}).get("name")) for node in nodes if clean_text((node or {}).get("name"))},
        key=str.lower,
    )
    if len(systems) < MIN_EXCP_SYSTEMS:
        raise RuntimeError(f"Suspicious EXCP dataset: only {len(systems)} systems")
    return systems


def match_systems(mahon_rows: list[list[Any]], excp_systems: list[str]) -> list[list[Any]]:
    excp_names = {clean_text(name).lower() for name in excp_systems}
    return sorted(
        [list(row) for row in mahon_rows if clean_text(row[0]).lower() in excp_names],
        key=lambda row: row[0].lower(),
    )


def post_apps_script(sheet: str, values: list[list[Any]]) -> None:
    if not APPS_SCRIPT_URL:
        raise RuntimeError("APPS_SCRIPT_URL is required unless --dry-run is used")
    if not APPS_SCRIPT_TOKEN:
        raise RuntimeError("APPS_SCRIPT_TOKEN is required unless --dry-run is used")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                APPS_SCRIPT_URL,
                json={
                    "action": "write",
                    "token": APPS_SCRIPT_TOKEN,
                    "sheet": sheet,
                    "values": values,
                },
                timeout=90,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("status") != "ok":
                raise RuntimeError(f"Apps Script error: {result}")
            return
        except Exception as exc:
            last_error = exc
            print(f"[Apps Script] Attempt {attempt}/3 failed: {exc}")
            if attempt < 3:
                time.sleep(5 * attempt)
    raise RuntimeError("Apps Script is unavailable") from last_error


def table_values(headers: list[str], rows: list[list[Any]]) -> list[list[Any]]:
    now = now_rome_string()
    values = [headers]
    for index, row in enumerate(rows):
        values.append(list(row) + ["", len(rows) if index == 0 else "", now if index == 0 else ""])
    return values


def run(dry_run: bool = False) -> dict[str, int]:
    started = time.time()
    mahon = fetch_powerplay()
    excp = fetch_excp()
    matched = match_systems(mahon, excp)

    mahon_values = table_values(
        ["Star system", "State", "Under", "Reinf", "Progress", "Updated", " ", "Systems", "Last Update"],
        mahon,
    )
    excp_rows = [[system] for system in excp]
    excp_values = table_values(
        ["Star system", "", "Controlled Systems", "Last Update"],
        excp_rows,
    )
    match_values = table_values(
        ["Star system", "State", "Under", "Reinf", "Progress", "Updated", " ", "Systems", "Last Update"],
        matched,
    )

    if not dry_run:
        post_apps_script(MAHON_SHEET, mahon_values)
        post_apps_script(EXCP_SHEET, excp_values)
        post_apps_script(MATCH_SHEET, match_values)

    summary = {"mahon": len(mahon), "excp": len(excp), "matches": len(matched)}
    print(
        f"\nCompleted in {time.time() - started:.1f}s | "
        f"Mahon={summary['mahon']} EXCP={summary['excp']} matches={summary['matches']}"
    )
    if dry_run:
        print("Dry run: no Google Sheet was modified")
    return summary


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
