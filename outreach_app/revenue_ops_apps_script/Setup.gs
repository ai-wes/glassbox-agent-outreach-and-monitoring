const SetupService = (() => {
  function setupProject() {
    const spreadsheetId = ConfigService.bindActiveSpreadsheet();
    DataModel.getTableNames().forEach((sheetName) => {
      ensureSheet_(sheetName);
      Repository.ensureHeaders(sheetName);
      formatSheet_(sheetName);
    });

    seedDefaultConfig_();
    seedDefaultRoutingRules_();
    PromptRegistry.reseedDefaults();
    ConfigService.getWebhookSecret();
    installTriggers_();
    applyValidationRules_();

    LogService.info('SetupService.setupProject', {
      message: 'Project setup completed.',
    });

    Utils.tryToast('Project setup complete', 'Revenue Ops');
    return {
      spreadsheetId: spreadsheetId,
      webhookSecret: ConfigService.getWebhookSecret(),
      runtime: ConfigService.describeRuntime(),
    };
  }

  function ensureSheet_(sheetName) {
    const spreadsheet = ConfigService.getSpreadsheet();
    let sheet = spreadsheet.getSheetByName(sheetName);
    if (!sheet) {
      sheet = spreadsheet.insertSheet(sheetName);
    }
    const headers = DataModel.getHeaders(sheetName);
    if (sheet.getLastRow() === 0) {
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    }
    sheet.setFrozenRows(DataModel.TABLES[sheetName].frozenRows || 1);
  }

  function formatSheet_(sheetName) {
    const sheet = Repository.getSheet(sheetName);
    const headers = DataModel.getHeaders(sheetName);
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    const headerRange = sheet.getRange(1, 1, 1, headers.length);
    headerRange.setFontWeight('bold');
    headerRange.setBackground('#e8f0fe');
    sheet.setFrozenRows(DataModel.TABLES[sheetName].frozenRows || 1);

    try {
      if (!sheet.getFilter()) {
        const rows = Math.max(sheet.getLastRow(), 2);
        sheet.getRange(1, 1, rows, headers.length).createFilter();
      }
    } catch (error) {
      // Ignore if filter already exists or the range is invalid.
    }

    const widths = {
      Dashboard: 180,
      Leads: 170,
      Accounts: 170,
      Contacts: 150,
      Deals: 150,
      Activities: 160,
      Tasks: 140,
      AI_Jobs: 160,
      AI_Outputs: 160,
      Prompt_Library: 220,
      PR_Events: 220,
      Radar_Opportunities: 180,
      Routing_Rules: 140,
      Config: 180,
      Logs: 150,
    };

    for (let i = 1; i <= headers.length; i += 1) {
      sheet.setColumnWidth(i, widths[sheetName] || 160);
    }
  }

  function seedDefaultConfig_() {
    DataModel.DEFAULT_CONFIG.forEach((item) => {
      ConfigService.setVisibleConfig(item.key, item.value, item.description);
    });
  }

  function seedDefaultRoutingRules_() {
    const existing = Repository.getAll('Routing_Rules');
    if (!existing.length) {
      Repository.append('Routing_Rules', DataModel.DEFAULT_ROUTING_RULES);
      return;
    }
    DataModel.DEFAULT_ROUTING_RULES.forEach((rule) => {
      const found = Repository.findByField('Routing_Rules', 'rule_id', rule.rule_id);
      if (!found) {
        Repository.append('Routing_Rules', [rule]);
      }
    });
  }

  function installTriggers_() {
    const spreadsheetId = ConfigService.getSpreadsheetId();
    const handlerNames = [
      'handleInstallableEdit',
      'processPendingJobs',
      'runHourlyMaintenance',
      'sendDailyDigests',
    ];

    ScriptApp.getProjectTriggers().forEach((trigger) => {
      if (handlerNames.indexOf(trigger.getHandlerFunction()) !== -1) {
        ScriptApp.deleteTrigger(trigger);
      }
    });

    ScriptApp.newTrigger('handleInstallableEdit')
      .forSpreadsheet(spreadsheetId)
      .onEdit()
      .create();

    ScriptApp.newTrigger('processPendingJobs')
      .timeBased()
      .everyMinutes(5)
      .create();

    ScriptApp.newTrigger('runHourlyMaintenance')
      .timeBased()
      .everyHours(1)
      .create();

    const digestHour = Utils.asInt(ConfigService.get('DIGEST_HOUR_LOCAL', '8'), 8);
    ScriptApp.newTrigger('sendDailyDigests')
      .timeBased()
      .everyDays(1)
      .atHour(Math.max(0, Math.min(23, digestHour)))
      .create();
  }

  function applyValidationRules_() {
    applyDropdownRule_('Leads', 'status', DataModel.ENUMS.LEAD_STATUS);
    applyDropdownRule_('Deals', 'stage', DataModel.ENUMS.DEAL_STAGE);
    applyDropdownRule_('Tasks', 'status', DataModel.ENUMS.TASK_STATUS);
    applyDropdownRule_('Tasks', 'priority', DataModel.ENUMS.TASK_PRIORITY);
    applyDropdownRule_('AI_Jobs', 'status', DataModel.ENUMS.JOB_STATUS);
    applyDropdownRule_('AI_Outputs', 'status', DataModel.ENUMS.OUTPUT_STATUS);
  }

  function applyDropdownRule_(sheetName, columnName, values) {
    const sheet = Repository.getSheet(sheetName);
    const headerMap = Repository.getHeaderMap(sheetName);
    const column = headerMap[columnName];
    if (!column) {
      return;
    }
    const rule = SpreadsheetApp.newDataValidation()
      .requireValueInList(values, true)
      .setAllowInvalid(true)
      .build();
    sheet.getRange(2, column, Math.max(sheet.getMaxRows() - 1, 1), 1).setDataValidation(rule);
  }

  return {
    setupProject,
  };
})();

function setupProject() {
  return SetupService.setupProject();
}
