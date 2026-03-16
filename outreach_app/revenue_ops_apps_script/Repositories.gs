const Repository = (() => {
  function getSpreadsheet_() {
    return ConfigService.getSpreadsheet();
  }

  function getSheet(sheetName) {
    const spreadsheet = getSpreadsheet_();
    let sheet = spreadsheet.getSheetByName(sheetName);
    if (!sheet) {
      const tableDef = DataModel.TABLES[sheetName];
      if (!tableDef) {
        throw new Error('Unknown sheet: ' + sheetName);
      }
      sheet = spreadsheet.insertSheet(sheetName);
      sheet.getRange(1, 1, 1, tableDef.headers.length).setValues([tableDef.headers]);
      sheet.setFrozenRows(tableDef.frozenRows || 1);
    }
    return sheet;
  }

  function getHeaders(sheetName) {
    const sheet = getSheet(sheetName);
    const lastColumn = Math.max(sheet.getLastColumn(), DataModel.getHeaders(sheetName).length);
    const values = sheet.getRange(1, 1, 1, lastColumn).getValues()[0];
    return values.map((value) => Utils.nonEmptyString(value)).filter((value) => value);
  }

  function getHeaderMap(sheetName) {
    const headers = getHeaders(sheetName);
    const map = {};
    headers.forEach((header, index) => {
      map[header] = index + 1;
    });
    return map;
  }

  function ensureHeaders(sheetName) {
    const sheet = getSheet(sheetName);
    const expectedHeaders = DataModel.getHeaders(sheetName);
    const actualHeaders = getHeaders(sheetName);
    const missingHeaders = expectedHeaders.filter((header) => actualHeaders.indexOf(header) === -1);
    if (!missingHeaders.length && actualHeaders.length === expectedHeaders.length) {
      return;
    }

    const existingRows = Math.max(sheet.getLastRow() - 1, 0);
    const existingValues = existingRows > 0
      ? sheet.getRange(2, 1, existingRows, Math.max(actualHeaders.length, 1)).getValues()
      : [];
    const existingRecords = existingValues.map((row) => rowToRecord_(actualHeaders, row, null));

    sheet.clear();
    sheet.getRange(1, 1, 1, expectedHeaders.length).setValues([expectedHeaders]);
    if (existingRecords.length) {
      const newRows = existingRecords.map((record) => recordToRow_(expectedHeaders, record));
      sheet.getRange(2, 1, newRows.length, expectedHeaders.length).setValues(newRows);
    }
    sheet.setFrozenRows(DataModel.TABLES[sheetName].frozenRows || 1);
  }

  function getAll(sheetName) {
    const sheet = getSheet(sheetName);
    const headers = getHeaders(sheetName);
    if (sheet.getLastRow() < 2) {
      return [];
    }
    const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, headers.length).getValues();
    return values.map((row, index) => rowToRecord_(headers, row, index + 2));
  }

  function getRecordByRow(sheetName, rowNumber) {
    const sheet = getSheet(sheetName);
    const headers = getHeaders(sheetName);
    if (rowNumber < 2 || rowNumber > sheet.getLastRow()) {
      return null;
    }
    const row = sheet.getRange(rowNumber, 1, 1, headers.length).getValues()[0];
    return rowToRecord_(headers, row, rowNumber);
  }

  function getById(sheetName, id) {
    const idField = DataModel.getIdField(sheetName);
    const rowNumber = findRowByFieldValue_(sheetName, idField, id);
    return rowNumber ? getRecordByRow(sheetName, rowNumber) : null;
  }

  function findByField(sheetName, field, value) {
    const rowNumber = findRowByFieldValue_(sheetName, field, value);
    return rowNumber ? getRecordByRow(sheetName, rowNumber) : null;
  }

  function filter(sheetName, predicate) {
    return getAll(sheetName).filter(predicate);
  }

  function append(sheetName, records) {
    const items = Utils.ensureArray(records);
    if (!items.length) {
      return [];
    }
    const sheet = getSheet(sheetName);
    const headers = getHeaders(sheetName);
    const rows = items.map((record) => recordToRow_(headers, record));
    const startRow = sheet.getLastRow() + 1;
    sheet.getRange(startRow, 1, rows.length, headers.length).setValues(rows);
    return items.map((record, index) => Object.assign({}, record, { __rowNumber: startRow + index }));
  }

  function updateRow(sheetName, rowNumber, patch) {
    const sheet = getSheet(sheetName);
    const headers = getHeaders(sheetName);
    const existing = getRecordByRow(sheetName, rowNumber);
    if (!existing) {
      throw new Error('Row ' + rowNumber + ' not found in ' + sheetName);
    }
    const merged = Object.assign({}, existing, patch || {});
    const row = recordToRow_(headers, merged);
    sheet.getRange(rowNumber, 1, 1, headers.length).setValues([row]);
    return Object.assign({}, merged, { __rowNumber: rowNumber });
  }

  function updateById(sheetName, id, patch) {
    const idField = DataModel.getIdField(sheetName);
    const rowNumber = findRowByFieldValue_(sheetName, idField, id);
    if (!rowNumber) {
      throw new Error('Record ' + id + ' not found in ' + sheetName);
    }
    return updateRow(sheetName, rowNumber, patch);
  }

  function upsertByField(sheetName, field, record) {
    const existingRow = findRowByFieldValue_(sheetName, field, record[field]);
    if (existingRow) {
      return updateRow(sheetName, existingRow, record);
    }
    return append(sheetName, [record])[0];
  }

  function batchUpdateRows(sheetName, patches) {
    const updates = Utils.ensureArray(patches);
    updates.forEach((item) => {
      updateRow(sheetName, item.rowNumber, item.patch);
    });
  }

  function getLatest(sheetName, predicate, sortFields) {
    const records = filter(sheetName, predicate);
    if (!records.length) {
      return null;
    }
    return Utils.sortByDateDesc(records, sortFields || ['updated_at', 'created_at'])[0];
  }

  function clearData(sheetName) {
    const sheet = getSheet(sheetName);
    if (sheet.getLastRow() > 1) {
      sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).clearContent();
    }
  }

  function rowToRecord_(headers, row, rowNumber) {
    const record = {};
    headers.forEach((header, index) => {
      const value = row[index];
      record[header] = value instanceof Date ? Utils.toIsoString(value) : value;
    });
    if (rowNumber) {
      record.__rowNumber = rowNumber;
    }
    return record;
  }

  function recordToRow_(headers, record) {
    return headers.map((header) => {
      const value = record[header];
      return Utils.cellValue(value);
    });
  }

  function findRowByFieldValue_(sheetName, field, value) {
    if (Utils.isBlank(value)) {
      return null;
    }
    const sheet = getSheet(sheetName);
    const headerMap = getHeaderMap(sheetName);
    const column = headerMap[field];
    if (!column || sheet.getLastRow() < 2) {
      return null;
    }
    const range = sheet.getRange(2, column, sheet.getLastRow() - 1, 1);
    const finder = range.createTextFinder(String(value));
    finder.matchEntireCell(true);
    finder.useRegularExpression(false);
    const match = finder.findNext();
    return match ? match.getRow() : null;
  }

  return {
    append,
    batchUpdateRows,
    clearData,
    ensureHeaders,
    filter,
    findByField,
    getAll,
    getById,
    getHeaders,
    getHeaderMap,
    getLatest,
    getRecordByRow,
    getSheet,
    updateById,
    updateRow,
    upsertByField,
  };
})();
