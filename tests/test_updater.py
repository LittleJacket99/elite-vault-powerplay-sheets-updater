import updater
from updater import (
    build_excp_mahon_values,
    build_excp_values,
    build_mahon_row,
    format_number,
    format_progress,
)


def occupied_system(name="14 Herculis"):
    return {
        "name": name,
        "powerplayState": "Exploited",
        "powerplayStateUndermining": 122,
        "powerplayStateReinforcement": 18,
        "powerplayStateControlProgress": 0.188,
        "updatedAt": None,
        "systemPowerplayPowers": {"totalCount": 1},
        "powerplayConflicts": {"totalCount": 0, "nodes": []},
    }


def test_formatters():
    assert format_number("12.0") == 12
    assert format_number("12.5") == 12.5
    assert format_progress(0.587608) == "58.7608%"
    assert format_progress(None) == ""


def test_occupied_mahon_row():
    assert build_mahon_row(occupied_system()) == [
        "14 Herculis",
        "Exploited",
        122,
        18,
        "18.8%",
        "",
    ]


def test_unoccupied_classification_uses_mahon_conflict():
    system = {
        "name": "Alpha",
        "powerplayState": "Unoccupied",
        "updatedAt": None,
        "systemPowerplayPowers": {"totalCount": 1},
        "powerplayConflicts": {
            "totalCount": 2,
            "nodes": [
                {"conflictProgress": 0.25, "updatedAt": None, "power": {"name": "Other"}},
                {
                    "conflictProgress": 0.5,
                    "updatedAt": None,
                    "power": {"name": "Edmund Mahon"},
                },
            ],
        },
    }
    assert build_mahon_row(system) == ["Alpha", "Contested", "", "", "50%", ""]


def test_unrelated_system_is_excluded():
    system = occupied_system()
    system["systemPowerplayPowers"] = {"totalCount": 0}
    assert build_mahon_row(system) is None


def test_sheet_builders_sort_and_count():
    systems = [occupied_system("Zulu"), occupied_system("alpha")]

    excp_values = build_excp_values(systems)
    assert [row[0] for row in excp_values[1:]] == ["alpha", "Zulu"]
    assert excp_values[1][2] == 2
    assert excp_values[2][2] == ""

    match_values, rows = build_excp_mahon_values(systems)
    assert [row[0] for row in rows] == ["alpha", "Zulu"]
    assert match_values[1][7] == 2
    assert len(match_values[0]) == len(match_values[1]) == 9


def test_apps_script_token_is_optional(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok"}

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(updater, "APPS_SCRIPT_URL", "https://example.test/exec")
    monkeypatch.setattr(updater, "APPS_SCRIPT_TOKEN", "")
    monkeypatch.setattr(updater.requests, "post", fake_post)

    updater.post_apps_script("EXCP", [["Star system"], ["Alpha"]])

    assert captured["json"] == {
        "action": "write",
        "sheet": "EXCP",
        "values": [["Star system"], ["Alpha"]],
    }
