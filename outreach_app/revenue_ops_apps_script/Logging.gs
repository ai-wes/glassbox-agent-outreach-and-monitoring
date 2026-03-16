const LogService = (() => {
  function log(level, functionName, details) {
    const payload = details || {};
    const message = Utils.truncate(payload.message || '', 1000);
    const row = [
      Utils.nowIso(),
      String(level || 'INFO').toUpperCase(),
      functionName || '',
      payload.entityType || '',
      payload.entityId || '',
      payload.jobId || '',
      message,
      payload.latencyMs || '',
      payload.responseCode || '',
      payload.traceId || Utils.uuid('trace')
    ];

    console.log(JSON.stringify({
      ts: row[0],
      level: row[1],
      function: row[2],
      entityType: row[3],
      entityId: row[4],
      jobId: row[5],
      message: row[6],
      latencyMs: row[7],
      responseCode: row[8],
      traceId: row[9],
    }));

    if (!ConfigService.getBoolean('LOG_TO_SHEET', true)) {
      return row[9];
    }

    try {
      const spreadsheet = ConfigService.getSpreadsheet();
      const sheet = spreadsheet.getSheetByName('Logs');
      if (sheet) {
        sheet.appendRow(row);
      }
    } catch (error) {
      console.error('Failed to write to Logs sheet: ' + Utils.stringifyError(error));
    }
    return row[9];
  }

  function info(functionName, details) {
    return log('INFO', functionName, details);
  }

  function warn(functionName, details) {
    return log('WARN', functionName, details);
  }

  function error(functionName, err, details) {
    const payload = Object.assign({}, details || {}, {
      message: (details && details.message ? details.message + ' | ' : '') + Utils.stringifyError(err),
    });
    return log('ERROR', functionName, payload);
  }

  return {
    error,
    info,
    log,
    warn,
  };
})();
