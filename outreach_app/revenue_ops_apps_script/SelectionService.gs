const SelectionService = (() => {
  function getSelectedContext() {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    if (!spreadsheet) {
      throw new Error('No active spreadsheet context.');
    }
    const sheet = spreadsheet.getActiveSheet();
    const row = sheet.getActiveCell().getRow();
    if (row < 2) {
      throw new Error('Select a data row before running this action.');
    }

    const sheetName = sheet.getName();
    const entityMap = {
      Leads: { entityType: 'lead', idField: 'lead_id' },
      Accounts: { entityType: 'account', idField: 'account_id' },
      Deals: { entityType: 'deal', idField: 'deal_id' },
      Activities: { entityType: 'activity', idField: 'activity_id' },
    };
    const mapping = entityMap[sheetName];
    if (!mapping) {
      throw new Error('Selected sheet is not supported by menu actions: ' + sheetName);
    }

    const record = Repository.getRecordByRow(sheetName, row);
    if (!record) {
      throw new Error('Could not read the selected record.');
    }

    return {
      sheetName: sheetName,
      entityType: mapping.entityType,
      entityId: record[mapping.idField],
      rowNumber: row,
      record: record,
    };
  }

  return {
    getSelectedContext,
  };
})();
