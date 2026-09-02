from updater import conflict_row, format_number, format_progress, match_systems, occupied_row


def test_formatters():
    assert format_number("12.0") == 12
    assert format_number("12.5") == 12.5
    assert format_progress(0.188) == "18.8%"
    assert format_progress(None) == ""


def test_occupied_row_accepts_supported_states():
    row = occupied_row(
        {
            "name": "14 Herculis",
            "powerplayState": "Exploited",
            "powerplayStateUndermining": 122,
            "powerplayStateReinforcement": 18,
            "powerplayStateControlProgress": 0.188,
            "updatedAt": None,
        }
    )
    assert row == ["14 Herculis", "Exploited", 122, 18, "18.8%", ""]


def test_conflict_classification():
    expansion = conflict_row(
        {
            "conflictProgress": 0.5,
            "updatedAt": None,
            "system": {
                "name": "Alpha",
                "powerplayState": "Unoccupied",
                "powerplayConflicts": {"totalCount": 1},
            },
        }
    )
    contested = conflict_row(
        {
            "conflictProgress": 0.25,
            "updatedAt": None,
            "system": {
                "name": "Beta",
                "powerplayState": "Unoccupied",
                "powerplayConflicts": {"totalCount": 2},
            },
        }
    )
    assert expansion[1] == "Expansion"
    assert contested[1] == "Contested"


def test_match_is_case_insensitive_and_sorted():
    mahon = [["Zulu", "Exploited"], ["alpha", "Fortified"], ["Other", "Stronghold"]]
    assert match_systems(mahon, ["ALPHA", "zulu"]) == [
        ["alpha", "Fortified"],
        ["Zulu", "Exploited"],
    ]
