const ConfigService = (() => {
  let inMemoryConfigMap = null;

  function getScriptProperties() {
    return PropertiesService.getScriptProperties();
  }

  function getDocumentProperties() {
    return PropertiesService.getDocumentProperties();
  }

  function bindActiveSpreadsheet() {
    const active = SpreadsheetApp.getActiveSpreadsheet();
    if (!active) {
      throw new Error('No active spreadsheet found. Run this from the bound revenue ops workbook.');
    }
    getScriptProperties().setProperty('REVENUE_SHEET_ID', active.getId());
    return active.getId();
  }

  function getSpreadsheetId() {
    const fromProps = getScriptProperties().getProperty('REVENUE_SHEET_ID');
    if (fromProps) {
      return fromProps;
    }
    try {
      const active = SpreadsheetApp.getActiveSpreadsheet();
      if (active) {
        const id = active.getId();
        getScriptProperties().setProperty('REVENUE_SHEET_ID', id);
        return id;
      }
    } catch (error) {
      // Ignore missing UI context.
    }
    throw new Error('REVENUE_SHEET_ID is not set. Run setupProject() from the bound spreadsheet first.');
  }

  function getSpreadsheet() {
    return SpreadsheetApp.openById(getSpreadsheetId());
  }

  function invalidateCache() {
    inMemoryConfigMap = null;
  }

  function getConfigMap() {
    if (inMemoryConfigMap) {
      return Object.assign({}, inMemoryConfigMap);
    }

    const config = {};
    try {
      const spreadsheet = getSpreadsheet();
      const sheet = spreadsheet.getSheetByName('Config');
      if (sheet && sheet.getLastRow() >= 2) {
        const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, 3).getValues();
        values.forEach((row) => {
          const key = Utils.nonEmptyString(row[0]);
          if (key) {
            config[key] = row[1];
          }
        });
      }
    } catch (error) {
      // Setup may call before the sheet exists.
    }

    inMemoryConfigMap = config;
    return Object.assign({}, config);
  }

  function get(key, defaultValue) {
    const scriptValue = getScriptProperties().getProperty(key);
    if (scriptValue !== null) {
      return scriptValue;
    }

    const documentValue = getDocumentProperties().getProperty(key);
    if (documentValue !== null) {
      return documentValue;
    }

    const configMap = getConfigMap();
    if (Object.prototype.hasOwnProperty.call(configMap, key) && configMap[key] !== '') {
      return configMap[key];
    }

    const matchingDefault = DataModel.DEFAULT_CONFIG.filter((item) => item.key === key)[0];
    if (matchingDefault) {
      return matchingDefault.value;
    }

    return defaultValue;
  }

  function getString(key, defaultValue) {
    const value = get(key, defaultValue);
    return value === null || value === undefined ? '' : String(value);
  }

  function getBoolean(key, defaultValue) {
    return Utils.parseBoolean(get(key, defaultValue), defaultValue);
  }

  function getNumber(key, defaultValue) {
    return Utils.asNumber(get(key, defaultValue), defaultValue);
  }

  function getStringArray(key) {
    const value = getString(key, '');
    return value
      .split(',')
      .map((item) => Utils.normalizeWhitespace(item))
      .filter((item) => item);
  }

  function setVisibleConfig(key, value, description) {
    const spreadsheet = getSpreadsheet();
    const sheet = spreadsheet.getSheetByName('Config');
    if (!sheet) {
      throw new Error('Config sheet does not exist.');
    }
    const lastRow = Math.max(sheet.getLastRow(), 1);
    if (lastRow >= 2) {
      const values = sheet.getRange(2, 1, lastRow - 1, 3).getValues();
      for (let i = 0; i < values.length; i += 1) {
        if (String(values[i][0]) === key) {
          sheet.getRange(i + 2, 2, 1, 2).setValues([[value, description || values[i][2] || '']]);
          invalidateCache();
          return;
        }
      }
    }
    sheet.appendRow([key, value, description || '']);
    invalidateCache();
  }

  function setSecret(key, value) {
    getScriptProperties().setProperty(key, String(value));
    invalidateCache();
  }

  function ensureSecret(key) {
    const existing = getScriptProperties().getProperty(key);
    if (existing) {
      return existing;
    }
    const created = Utils.sha256Hex(Utils.uuid(key) + Utils.nowIso()).slice(0, 48);
    setSecret(key, created);
    return created;
  }

  function getOpenAiConfig() {
    const apiKey = getString('OPENAI_API_KEY', '');
    if (!apiKey) {
      throw new Error('OPENAI_API_KEY is missing. Set it in Script Properties.');
    }
    return {
      apiKey,
      baseUrl: getString('OPENAI_BASE_URL', 'https://api.openai.com/v1').replace(/\/+$/, ''),
      model: getString('OPENAI_MODEL', 'gpt-5.4'),
      reasoningEffort: getString('OPENAI_REASONING_EFFORT', 'low'),
      verbosity: getString('OPENAI_VERBOSITY', 'low'),
      maxOutputTokens: getNumber('OPENAI_MAX_OUTPUT_TOKENS', 2500),
    };
  }

  function getOutreachApiConfig() {
    const baseUrl = getString('OUTREACH_API_BASE_URL', '').replace(/\/+$/, '');
    if (!baseUrl) {
      throw new Error('OUTREACH_API_BASE_URL is missing. Set it in the Config sheet.');
    }
    return {
      baseUrl,
      apiKey: getString('OUTREACH_API_KEY', ''),
      syncLimit: getNumber('PLATFORM_SYNC_LIMIT', 100),
      platformSyncEnabled: getBoolean('ENABLE_PLATFORM_SYNC', true),
    };
  }

  function getWebhookSecret() {
    return ensureSecret('WEBHOOK_SHARED_SECRET');
  }

  function getRoundRobinOwners() {
    return getStringArray('ROUND_ROBIN_OWNERS');
  }

  function getManagerDigestRecipients() {
    return getStringArray('MANAGER_DIGEST_RECIPIENTS');
  }

  function describeRuntime() {
    const outreachBaseUrl = getString('OUTREACH_API_BASE_URL', '').replace(/\/+$/, '');
    return {
      spreadsheetId: getSpreadsheetId(),
      webhookSecretPresent: !!getScriptProperties().getProperty('WEBHOOK_SHARED_SECRET'),
      openAiConfigured: !!getScriptProperties().getProperty('OPENAI_API_KEY'),
      outreachApiConfigured: !!getString('OUTREACH_API_KEY', ''),
      outreachBaseUrl: outreachBaseUrl,
      automationPaused: getBoolean('AUTOMATION_PAUSED', false),
      platformSyncEnabled: getBoolean('ENABLE_PLATFORM_SYNC', true),
      workerBatchSize: getNumber('WORKER_BATCH_SIZE', 8),
      logToSheet: getBoolean('LOG_TO_SHEET', true),
    };
  }

  return {
    bindActiveSpreadsheet,
    describeRuntime,
    get,
    getBoolean,
    getConfigMap,
    getDocumentProperties,
    getManagerDigestRecipients,
    getNumber,
    getOpenAiConfig,
    getRoundRobinOwners,
    getScriptProperties,
    getSpreadsheet,
    getSpreadsheetId,
    getString,
    getStringArray,
    getWebhookSecret,
    getOutreachApiConfig,
    invalidateCache,
    setSecret,
    setVisibleConfig,
  };
})();
