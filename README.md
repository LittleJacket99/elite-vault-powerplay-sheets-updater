# Elite Vault Powerplay Sheets Updater

[![Data source: EliteHub Vault](https://img.shields.io/badge/Data%20source-EliteHub%20Vault-5865f2)](https://github.com/jovanblazek/elitehub-vault)

A small Python automation that retrieves Elite Dangerous data from the
[EliteHub Vault](https://github.com/jovanblazek/elitehub-vault) GraphQL API and
synchronizes it with Google Sheets through a Google Apps Script web app.

The updater currently tracks:

- Edmund Mahon occupied systems: `Stronghold`, `Fortified`, and `Exploited`;
- Edmund Mahon `Expansion` and `Contested` systems;
- systems controlled by `Expanders Corp`;
- the intersection between the Mahon and Expanders Corp datasets.

EliteHub Vault is the **only galaxy-data source** used by this project. There is
no Inara scraper or fallback. If Vault is unavailable, validation fails or a
query cannot be completed, the run stops before any Google Sheet is modified.

This public repository is provided as a reference implementation and is not the
production updater used by its maintainer. It contains no scheduled GitHub
Actions workflow and does not run automatically.

An inactive workflow example is available in
[`examples/github-actions/update.yml`](examples/github-actions/update.yml).
GitHub does not execute files from the `examples` directory.

## Data flow

1. The script queries the read-only Vault GraphQL endpoint with pagination.
2. It handles rate limits, retries and GraphQL query-cost reductions.
3. Sanity checks reject unexpectedly small datasets.
4. Only after every dataset succeeds are the three sheets updated.

## Requirements

- Python 3.11 or newer;
- a deployed Google Apps Script web app that accepts the JSON payload described
  below;
- a Google Sheet containing `Mahon`, `EXCP`, and `EXCP_Mahon` tabs (names can be
  changed with environment variables).

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set the required environment variable without committing it:

```bash
export APPS_SCRIPT_URL="https://script.google.com/macros/s/.../exec"
export APPS_SCRIPT_TOKEN="replace-with-a-long-random-secret"
export PROJECT_REPOSITORY_URL="https://github.com/YOUR_USERNAME/elite-vault-sheets-updater"
python updater.py
```

To test Vault queries and sanity checks without changing Sheets:

```bash
python updater.py --dry-run
```

## Google Apps Script setup

A generic receiver is included in [`apps-script/Code.gs`](apps-script/Code.gs).
It is an example only and is not connected to the maintainer's spreadsheet.

To use it in your own Google account:

1. Create an Apps Script project and paste the contents of `Code.gs`.
2. In **Project Settings → Script Properties**, add:
   - `SPREADSHEET_ID`: the ID of your destination spreadsheet;
   - `API_TOKEN`: a long random secret of your choice.
3. Deploy it as a web app and keep its deployment URL private.
4. Use the same secret as `APPS_SCRIPT_TOKEN` when running the Python updater.

The receiver accepts writes only to `Mahon`, `EXCP`, and `EXCP_Mahon`. Change
`ALLOWED_SHEETS` in the example if you use different sheet names.

## Apps Script contract

For each sheet, the updater sends an HTTP `POST` with JSON shaped like this:

```json
{
  "action": "write",
  "token": "shared-secret",
  "sheet": "Mahon",
  "values": [["Star system", "State"], ["14 Herculis", "Exploited"]]
}
```

The endpoint must return JSON containing:

```json
{"status": "ok"}
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `APPS_SCRIPT_URL` | required | Private Apps Script web-app endpoint |
| `APPS_SCRIPT_TOKEN` | required | Secret shared with the Apps Script receiver |
| `PROJECT_REPOSITORY_URL` | empty | Added to the Vault `User-Agent` |
| `VAULT_URL` | Vault public endpoint | GraphQL endpoint |
| `VAULT_BATCH_SIZE` | `100` | Initial pagination size |
| `VAULT_MIN_BATCH_SIZE` | `10` | Smallest batch after cost errors |
| `VAULT_MAX_RETRIES` | `3` | Attempts per Vault request |
| `VAULT_REQUEST_DELAY` | `1.5` | Delay between pages in seconds |
| `MIN_MAHON_SYSTEMS` | `1000` | Mahon sanity threshold |
| `MIN_EXCP_SYSTEMS` | `150` | EXCP sanity threshold |
| `EXCP_FACTION_ID` | Expanders Corp UUID | Controlling faction filter |
| `MAHON_SHEET` | `Mahon` | Destination sheet |
| `EXCP_SHEET` | `EXCP` | Destination sheet |
| `MATCH_SHEET` | `EXCP_Mahon` | Destination intersection sheet |

## Optional GitHub Actions example

The file [`examples/github-actions/update.yml`](examples/github-actions/update.yml)
shows how a fork can run the updater manually or on a daily schedule. It is
deliberately stored outside `.github/workflows`, so it is inert in this
repository. Enabling it requires copying the file and configuring both
`APPS_SCRIPT_URL` and `APPS_SCRIPT_TOKEN` as repository secrets.

## Attribution

Powerplay, faction and system data are provided by
[EliteHub Vault](https://github.com/jovanblazek/elitehub-vault), which processes
data submitted through the Elite Dangerous Data Network (EDDN).

Thanks to the EliteHub Vault maintainers and contributors for making the API
available to community projects.

This project is an independent community tool and is not affiliated with or
endorsed by Frontier Developments. Elite Dangerous and all related marks are
property of Frontier Developments plc.

## License

[MIT](LICENSE)
