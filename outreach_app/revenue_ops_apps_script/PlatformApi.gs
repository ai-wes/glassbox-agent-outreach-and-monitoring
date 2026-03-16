const PlatformApi = (() => {
  function fetchStatus() {
    return fetchJson_('/agent/platform/status');
  }

  function fetchPrEvents(limit) {
    const cappedLimit = normalizeLimit_(limit);
    return fetchJson_('/agent/platform/pr/events?limit=' + cappedLimit);
  }

  function fetchRadarOpportunities(limit) {
    const cappedLimit = normalizeLimit_(limit);
    return fetchJson_('/agent/platform/radar/opportunities?limit=' + cappedLimit);
  }

  function fetchBundle(limit) {
    const cfg = ConfigService.getOutreachApiConfig();
    const cappedLimit = normalizeLimit_(limit || cfg.syncLimit);
    const baseUrl = cfg.baseUrl;
    const headers = buildHeaders_(cfg.apiKey);

    const requests = [
      buildRequest_(baseUrl + '/agent/platform/status', headers),
      buildRequest_(baseUrl + '/agent/platform/pr/events?limit=' + cappedLimit, headers),
      buildRequest_(baseUrl + '/agent/platform/radar/opportunities?limit=' + cappedLimit, headers),
    ];

    const startedAt = new Date().getTime();
    const responses = UrlFetchApp.fetchAll(requests);
    const latencyMs = new Date().getTime() - startedAt;

    const parsed = responses.map((response, index) => {
      const path = [
        '/agent/platform/status',
        '/agent/platform/pr/events',
        '/agent/platform/radar/opportunities',
      ][index];
      return parseResponse_(response, path);
    });

    LogService.info('PlatformApi.fetchBundle', {
      message: 'Fetched platform bundle from outreach host.',
      latencyMs: latencyMs,
      responseCode: 200,
    });

    return {
      status: parsed[0],
      prEvents: parsed[1],
      radarOpportunities: parsed[2],
    };
  }

  function buildRequest_(url, headers) {
    return {
      url: url,
      method: 'get',
      muteHttpExceptions: true,
      headers: headers,
    };
  }

  function fetchJson_(path) {
    const cfg = ConfigService.getOutreachApiConfig();
    const url = cfg.baseUrl + path;
    const startedAt = new Date().getTime();
    const response = UrlFetchApp.fetch(url, {
      method: 'get',
      muteHttpExceptions: true,
      headers: buildHeaders_(cfg.apiKey),
    });
    const latencyMs = new Date().getTime() - startedAt;
    const parsed = parseResponse_(response, path);
    LogService.info('PlatformApi.fetchJson', {
      message: 'Fetched ' + path,
      latencyMs: latencyMs,
      responseCode: response.getResponseCode(),
    });
    return parsed;
  }

  function parseResponse_(response, path) {
    const code = response.getResponseCode();
    const text = response.getContentText();
    const parsed = Utils.parseJson(text, null);
    if (code < 200 || code >= 300) {
      const detail = parsed && parsed.detail ? parsed.detail : text;
      throw new Error('Platform API request failed for ' + path + ' with ' + code + ': ' + detail);
    }
    return parsed;
  }

  function buildHeaders_(apiKey) {
    const headers = {
      Accept: 'application/json',
    };
    if (apiKey) {
      headers['X-API-Key'] = apiKey;
    }
    return headers;
  }

  function normalizeLimit_(value) {
    const limit = Utils.asInt(value, 100);
    return Math.max(1, Math.min(500, limit || 100));
  }

  return {
    fetchBundle,
    fetchPrEvents,
    fetchRadarOpportunities,
    fetchStatus,
  };
})();
