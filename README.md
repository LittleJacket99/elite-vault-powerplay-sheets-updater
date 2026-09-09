# Elite Vault Powerplay Sheets Updater

[![Data source: EliteHub Vault](https://img.shields.io/badge/Data%20source-EliteHub%20Vault-5865f2)](https://github.com/jovanblazek/elitehub-vault)

A small Python automation that retrieves Elite Dangerous data from the
[EliteHub Vault](https://github.com/jovanblazek/elitehub-vault) GraphQL API and
synchronizes it with Google Sheets through a Google Apps Script web app.

This version is optimized for a specific question: which systems controlled by
`Expanders Corp` are occupied or contested by Edmund Mahon? It queries only the
EXCP-controlled systems and requests the relevant powerplay fields in the same
paginated Vault query. It does not download Mahon's complete system list.

The updater writes two sheets:

- `EXCP`: every system controlled by Expanders Corp;
- `EXCP_Mahon`: the EXCP systems related to Edmund Mahon, classified as
  `Stronghold`, `Fortified`, `Exploited`, `Expansion`, or `Contested`.

EliteHub Vault is the **only galaxy-data source** used by this project. There is
no Inara scraper or fallback. If Vault is unavailable, a query cannot be
completed, or the sanity checks fail, the run stops before either sheet is
modified.

This repository includes an active GitHub Actions workflow in
[`.github/workflows/update.yml`](.github/workflows/update.yml). It can be run
manually and is scheduled once per day. A separate reusable reference remains
available in [`examples/github-actions/update.yml`](examples/github-actions/update.yml).

## Data flow

1. Query Vault for systems whose controlling faction is Expanders Corp.
2. Retrieve each system's state, progress, Mahon relation, and conflicts in the
   same paginated query.
3. Handle rate limits, transient failures, and GraphQL query-cost reductions.
4. Reject unexpectedly small `EXCP` or `EXCP_Mahon` results.
5. Build both tables in memory, then send them to Google Apps Script.

## Requirements

- Python 3.11 or newer;
- a deployed Google Apps Script web app that accepts the JSON payload described
  below;
- a Google Sheet containing `EXCP` and `EXCP_Mahon` tabs (the names are
  configurable).

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set the required environment variables without committing them:

```bash
export APPS_SCRIPT_URL="https://script.google.com/macros/s/.../exec"
export APPS_SCRIPT_TOKEN="replace-with-a-long-random-secret"
export PROJECT_REPOSITORY_URL="https://github.com/YOUR_USERNAME/elite-vault-powerplay-sheets-updater"
python updater.py
```

To query and validate Vault without changing Sheets, neither Apps Script
variable is required:

```bash
python updater.py --dry-run
```

## Google Apps Script setup

A generic receiver is included in [`apps-script/Code.gs`](apps-script/Code.gs).
It is an example only and is not connected to the maintainer's spreadsheet.

1. Create an Apps Script project and paste the contents of `Code.gs`.
2. In **Project Settings → Script Properties**, add:
   - `SPREADSHEET_ID`: the ID of the destination spreadsheet;
   - `API_TOKEN`: a long random secret of your choice.
3. Deploy it as a web app and keep its deployment URL private.
4. Use the same secret as `APPS_SCRIPT_TOKEN` when running the updater.

The receiver accepts writes only to `EXCP` and `EXCP_Mahon`. Change
`ALLOWED_SHEETS` if you configure different names.

## Apps Script contract

For each sheet, the updater sends an HTTP `POST` like this:

```json
{
  "action": "write",
  "token": "shared-secret",
  "sheet": "EXCP",
  "values": [["Star system", "", "Controlled Systems"], ["14 Herculis", "", 245]]
}
```

The endpoint must return JSON containing:

```json
{"status": "ok"}
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `APPS_SCRIPT_URL` | required for writes | Private Apps Script web-app endpoint |
| `APPS_SCRIPT_TOKEN` | required for writes | Secret shared with the Apps Script receiver |
| `PROJECT_REPOSITORY_URL` | empty | Added to the Vault `User-Agent` |
| `VAULT_URL` | Vault public endpoint | GraphQL endpoint |
| `VAULT_BATCH_SIZE` | `50` | Initial pagination size |
| `VAULT_MIN_BATCH_SIZE` | `10` | Smallest batch after query-cost errors |
| `VAULT_MAX_RETRIES` | `5` | Attempts per Vault request |
| `VAULT_REQUEST_DELAY` | `1.5` | Delay between pages in seconds |
| `VAULT_TIMEOUT` | `60` | HTTP timeout in seconds |
| `MIN_EXCP_SYSTEMS` | `150` | EXCP sanity threshold |
| `MIN_MATCH_SYSTEMS` | `1` | EXCP_Mahon sanity threshold |
| `EXCP_FACTION_ID` | Expanders Corp UUID | Controlling-faction filter |
| `MAHON_POWER_ID` | Edmund Mahon UUID | Power relation filter |
| `MAHON_POWER_NAME` | `Edmund Mahon` | Conflict-owner match |
| `EXCP_SHEET` | `EXCP` | EXCP destination sheet |
| `MATCH_SHEET` | `EXCP_Mahon` | Intersection destination sheet |

## GitHub Actions

The active workflow runs every day at `17:37 UTC`, after which it waits for a
random delay of up to 10 minutes before querying Vault. It can also be started
from the GitHub Actions page with `workflow_dispatch`.

The repository must contain these GitHub Actions secrets:

- `APPS_SCRIPT_URL`;
- `APPS_SCRIPT_TOKEN`.

The inactive copy in
[`examples/github-actions/update.yml`](examples/github-actions/update.yml) can
be reused by forks or as a reference without being executed by GitHub.

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check updater.py tests
```

## Attribution

Powerplay, faction, and system data are provided by
[EliteHub Vault](https://github.com/jovanblazek/elitehub-vault), which processes
data submitted through the Elite Dangerous Data Network (EDDN).

Thanks to the EliteHub Vault maintainers and contributors for making the API
available to community projects.

This project is an independent community tool and is not affiliated with or
endorsed by Frontier Developments. Elite Dangerous and all related marks are
property of Frontier Developments plc.

## License

[MIT](LICENSE)
