const Utils = (() => {
  function getTimeZone() {
    return Session.getScriptTimeZone() || 'America/Los_Angeles';
  }

  function nowIso() {
    return Utilities.formatDate(new Date(), getTimeZone(), "yyyy-MM-dd'T'HH:mm:ssXXX");
  }

  function todayIso() {
    return Utilities.formatDate(new Date(), getTimeZone(), 'yyyy-MM-dd');
  }

  function toIsoString(value) {
    if (value === null || value === undefined || value === '') {
      return '';
    }
    const date = value instanceof Date ? value : new Date(value);
    if (isNaN(date.getTime())) {
      return '';
    }
    return Utilities.formatDate(date, getTimeZone(), "yyyy-MM-dd'T'HH:mm:ssXXX");
  }

  function toDate(value) {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    if (value instanceof Date) {
      return value;
    }
    const date = new Date(value);
    return isNaN(date.getTime()) ? null : date;
  }

  function addDays(value, days) {
    const date = toDate(value) || new Date();
    date.setDate(date.getDate() + days);
    return toIsoString(date);
  }

  function addHours(value, hours) {
    const date = toDate(value) || new Date();
    date.setHours(date.getHours() + hours);
    return toIsoString(date);
  }

  function addMinutes(value, minutes) {
    const date = toDate(value) || new Date();
    date.setMinutes(date.getMinutes() + minutes);
    return toIsoString(date);
  }

  function isBlank(value) {
    return value === null || value === undefined || String(value).trim() === '';
  }

  function nonEmptyString(value) {
    return isBlank(value) ? '' : String(value).trim();
  }

  function truncate(value, maxLength) {
    const str = String(value === null || value === undefined ? '' : value);
    if (str.length <= maxLength) {
      return str;
    }
    return str.slice(0, Math.max(0, maxLength - 1)) + '…';
  }

  function limitCellText(value) {
    return truncate(value, 49000);
  }

  function uuid(prefix) {
    const base = Utilities.getUuid().replace(/-/g, '');
    return prefix ? (prefix + '_' + base) : base;
  }

  function stableStringify(value) {
    if (value === null || value === undefined) {
      return JSON.stringify(value);
    }
    if (value instanceof Date) {
      return JSON.stringify(toIsoString(value));
    }
    if (Array.isArray(value)) {
      return '[' + value.map((item) => stableStringify(item)).join(',') + ']';
    }
    if (typeof value === 'object') {
      const keys = Object.keys(value).sort();
      return '{' + keys.map((key) => JSON.stringify(key) + ':' + stableStringify(value[key])).join(',') + '}';
    }
    return JSON.stringify(value);
  }

  function sha256Hex(value) {
    const input = String(value === null || value === undefined ? '' : value);
    const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, input, Utilities.Charset.UTF_8);
    return digest.map((b) => {
      const byte = (b + 256) % 256;
      const hex = byte.toString(16);
      return hex.length === 1 ? '0' + hex : hex;
    }).join('');
  }

  function hashObject(value) {
    return sha256Hex(stableStringify(value));
  }

  function normalizeWhitespace(value) {
    return nonEmptyString(value).replace(/\s+/g, ' ');
  }

  function normalizeEmail(value) {
    return normalizeWhitespace(value).toLowerCase();
  }

  function normalizeDomain(value) {
    const input = normalizeWhitespace(value).toLowerCase();
    if (!input) {
      return '';
    }
    let normalized = input.replace(/^https?:\/\//, '').replace(/^www\./, '');
    normalized = normalized.split('/')[0];
    normalized = normalized.split('?')[0];
    normalized = normalized.split('#')[0];
    normalized = normalized.replace(/[^a-z0-9.-]/g, '');
    return normalized;
  }

  function domainFromEmail(email) {
    const normalized = normalizeEmail(email);
    if (!normalized || normalized.indexOf('@') === -1) {
      return '';
    }
    return normalizeDomain(normalized.split('@')[1]);
  }

  function normalizeCompanyName(value) {
    return normalizeWhitespace(value);
  }

  function splitName(fullName) {
    const name = normalizeWhitespace(fullName);
    if (!name) {
      return { firstName: '', lastName: '' };
    }
    const parts = name.split(' ');
    if (parts.length === 1) {
      return { firstName: parts[0], lastName: '' };
    }
    return {
      firstName: parts.slice(0, -1).join(' '),
      lastName: parts.slice(-1)[0]
    };
  }

  function asNumber(value, defaultValue) {
    if (value === null || value === undefined || value === '') {
      return defaultValue === undefined ? null : defaultValue;
    }
    const num = Number(value);
    return isNaN(num) ? (defaultValue === undefined ? null : defaultValue) : num;
  }

  function asInt(value, defaultValue) {
    const num = asNumber(value, defaultValue);
    if (num === null) {
      return null;
    }
    return Math.round(num);
  }

  function clamp(value, min, max) {
    if (value === null || value === undefined || value === '') {
      return value;
    }
    return Math.min(max, Math.max(min, value));
  }

  function parseBoolean(value, defaultValue) {
    if (typeof value === 'boolean') {
      return value;
    }
    const normalized = normalizeWhitespace(String(value || '')).toLowerCase();
    if (normalized === 'true' || normalized === 'yes' || normalized === '1') {
      return true;
    }
    if (normalized === 'false' || normalized === 'no' || normalized === '0') {
      return false;
    }
    return defaultValue === undefined ? false : defaultValue;
  }

  function ensureArray(value) {
    if (Array.isArray(value)) {
      return value;
    }
    if (value === null || value === undefined || value === '') {
      return [];
    }
    return [value];
  }

  function stripSecrets(obj) {
    if (obj === null || obj === undefined) {
      return obj;
    }
    const cloned = parseJson(JSON.stringify(obj), {});
    if (cloned && typeof cloned === 'object') {
      delete cloned.secret;
      delete cloned.api_key;
      delete cloned.authorization;
    }
    return cloned;
  }

  function parseJson(value, defaultValue) {
    if (value === null || value === undefined || value === '') {
      return defaultValue === undefined ? null : defaultValue;
    }
    if (typeof value === 'object') {
      return value;
    }
    try {
      return JSON.parse(String(value));
    } catch (error) {
      return defaultValue === undefined ? null : defaultValue;
    }
  }

  function cellValue(value) {
    if (value === null || value === undefined) {
      return '';
    }
    if (value instanceof Date) {
      return toIsoString(value);
    }
    if (Array.isArray(value) || typeof value === 'object') {
      return limitCellText(stableStringify(value));
    }
    return value;
  }

  function rowHashFromFields(record, fields) {
    const projection = {};
    fields.forEach((field) => {
      projection[field] = record[field];
    });
    return hashObject(projection);
  }

  function renderTemplate(template, variables) {
    return String(template || '').replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (match, key) => {
      const value = variables[key];
      if (value === null || value === undefined) {
        return '';
      }
      if (typeof value === 'object') {
        return JSON.stringify(value, null, 2);
      }
      return String(value);
    });
  }

  function pick(record, fields) {
    const output = {};
    fields.forEach((field) => {
      output[field] = record ? record[field] : '';
    });
    return output;
  }

  function mergeUniqueStrings(first, second) {
    const seen = {};
    const output = [];
    ensureArray(first).concat(ensureArray(second)).forEach((item) => {
      const normalized = normalizeWhitespace(item);
      if (normalized && !seen[normalized.toLowerCase()]) {
        seen[normalized.toLowerCase()] = true;
        output.push(normalized);
      }
    });
    return output;
  }

  function htmlEscape(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function nl2br(value) {
    return String(value === null || value === undefined ? '' : value).replace(/\n/g, '<br>');
  }

  function sanitizeEmailHtml(html) {
    let sanitized = String(html || '');
    sanitized = sanitized.replace(/<\s*(script|style|iframe|object|embed)[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi, '');
    sanitized = sanitized.replace(/\son[a-z]+\s*=\s*(['"]).*?\1/gi, '');
    sanitized = sanitized.replace(/\sjavascript:/gi, '');
    return sanitized;
  }

  function secureEquals(a, b) {
    const left = String(a || '');
    const right = String(b || '');
    const leftDigest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, left, Utilities.Charset.UTF_8);
    const rightDigest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, right, Utilities.Charset.UTF_8);
    if (leftDigest.length !== rightDigest.length) {
      return false;
    }
    let mismatch = 0;
    for (let i = 0; i < leftDigest.length; i += 1) {
      mismatch |= ((leftDigest[i] + 256) % 256) ^ ((rightDigest[i] + 256) % 256);
    }
    return mismatch === 0;
  }

  function sortByDateDesc(records, fieldNames) {
    const fields = ensureArray(fieldNames);
    return records.slice().sort((a, b) => {
      const aDate = getFirstDate_(a, fields);
      const bDate = getFirstDate_(b, fields);
      return bDate - aDate;
    });
  }

  function getFirstDate_(record, fields) {
    for (let i = 0; i < fields.length; i += 1) {
      const field = fields[i];
      const date = toDate(record[field]);
      if (date) {
        return date.getTime();
      }
    }
    return 0;
  }

  function chunk(items, size) {
    const output = [];
    for (let i = 0; i < items.length; i += size) {
      output.push(items.slice(i, i + size));
    }
    return output;
  }

  function tryToast(message, title) {
    try {
      const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
      if (spreadsheet) {
        spreadsheet.toast(message, title || 'Revenue Ops', 5);
      }
    } catch (error) {
      // Ignore when there is no UI context.
    }
  }

  function stringifyError(error) {
    if (!error) {
      return 'Unknown error';
    }
    if (typeof error === 'string') {
      return error;
    }
    if (error.stack) {
      return String(error.stack);
    }
    if (error.message) {
      return String(error.message);
    }
    return stableStringify(error);
  }

  function markdownBullets(items) {
    return ensureArray(items)
      .filter((item) => !isBlank(item))
      .map((item) => '- ' + String(item))
      .join('\n');
  }

  function formatDateOnly(value) {
    const date = toDate(value);
    if (!date) {
      return '';
    }
    return Utilities.formatDate(date, getTimeZone(), 'yyyy-MM-dd');
  }

  return {
    addDays,
    addHours,
    addMinutes,
    asInt,
    asNumber,
    cellValue,
    clamp,
    domainFromEmail,
    ensureArray,
    formatDateOnly,
    getTimeZone,
    hashObject,
    htmlEscape,
    isBlank,
    limitCellText,
    markdownBullets,
    mergeUniqueStrings,
    nl2br,
    nonEmptyString,
    normalizeCompanyName,
    normalizeDomain,
    normalizeEmail,
    normalizeWhitespace,
    nowIso,
    parseBoolean,
    parseJson,
    pick,
    renderTemplate,
    rowHashFromFields,
    sanitizeEmailHtml,
    secureEquals,
    sha256Hex,
    sortByDateDesc,
    stripSecrets,
    splitName,
    stableStringify,
    stringifyError,
    todayIso,
    toDate,
    toIsoString,
    truncate,
    tryToast,
    uuid,
    chunk,
  };
})();
