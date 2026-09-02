/**
 * Example Google Apps Script receiver for Elite Vault Sheets Updater.
 *
 * Required Script Properties:
 *   SPREADSHEET_ID - destination Google Sheet ID
 *   API_TOKEN      - long random secret shared with APPS_SCRIPT_TOKEN
 */

const ALLOWED_SHEETS = new Set(["Mahon", "EXCP", "EXCP_Mahon"]);


function jsonResponse_(body) {
  return ContentService
    .createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}


function doPost(e) {
  const lock = LockService.getScriptLock();

  try {
    if (!lock.tryLock(30000)) {
      throw new Error("Another update is already running");
    }

    const properties = PropertiesService.getScriptProperties();
    const spreadsheetId = properties.getProperty("SPREADSHEET_ID");
    const expectedToken = properties.getProperty("API_TOKEN");

    if (!spreadsheetId || !expectedToken) {
      throw new Error("SPREADSHEET_ID and API_TOKEN must be configured");
    }

    if (!e || !e.postData || !e.postData.contents) {
      throw new Error("Missing JSON request body");
    }

    const payload = JSON.parse(e.postData.contents);

    if (payload.token !== expectedToken) {
      return jsonResponse_({status: "error", message: "Unauthorized"});
    }

    if (payload.action !== "write") {
      throw new Error("Unsupported action");
    }

    if (!ALLOWED_SHEETS.has(payload.sheet)) {
      throw new Error("Sheet is not allowed");
    }

    const values = payload.values;

    if (!Array.isArray(values) || values.length === 0) {
      throw new Error("values must be a non-empty array");
    }

    const columnCount = Array.isArray(values[0]) ? values[0].length : 0;
    const rectangular = columnCount > 0 && values.every(
      row => Array.isArray(row) && row.length === columnCount
    );

    if (!rectangular) {
      throw new Error("values must be a rectangular two-dimensional array");
    }

    const spreadsheet = SpreadsheetApp.openById(spreadsheetId);
    const sheet = spreadsheet.getSheetByName(payload.sheet);

    if (!sheet) {
      throw new Error(`Sheet not found: ${payload.sheet}`);
    }

    sheet.clearContents();
    sheet.getRange(1, 1, values.length, columnCount).setValues(values);

    return jsonResponse_({
      status: "ok",
      sheet: payload.sheet,
      rows: values.length,
    });

  } catch (error) {
    return jsonResponse_({
      status: "error",
      message: String(error && error.message ? error.message : error),
    });

  } finally {
    if (lock.hasLock()) {
      lock.releaseLock();
    }
  }
}
