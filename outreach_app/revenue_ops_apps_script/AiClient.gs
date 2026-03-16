const AiClient = (() => {
  function generateStructuredJson(jobType, prompt) {
    const cfg = ConfigService.getOpenAiConfig();
    const schemaInfo = AiSchemas.get(jobType);

    const payload = {
      model: cfg.model,
      input: [
        { role: 'developer', content: prompt.systemText },
        { role: 'user', content: prompt.userText }
      ],
      text: {
        verbosity: cfg.verbosity,
        format: {
          type: 'json_schema',
          name: schemaInfo.name,
          strict: true,
          schema: schemaInfo.schema,
        }
      },
      reasoning: {
        effort: cfg.reasoningEffort
      },
      max_output_tokens: cfg.maxOutputTokens,
      store: false
    };

    const start = new Date().getTime();
    const response = fetchWithRetry_(cfg.baseUrl + '/responses', payload, cfg.apiKey);
    const latency = new Date().getTime() - start;
    const parsed = extractStructuredOutput_(response);

    LogService.info('AiClient.generateStructuredJson', {
      message: 'AI response generated for ' + jobType,
      latencyMs: latency,
      responseCode: 200,
    });

    return {
      parsed,
      rawResponse: response,
      modelName: response.model || cfg.model,
      schemaVersion: schemaInfo.schemaVersion,
      responseId: response.id || '',
      status: response.status || '',
      confidence: parsed && parsed.confidence !== undefined ? parsed.confidence : '',
    };
  }

  function fetchWithRetry_(url, payload, apiKey) {
    const maxAttempts = 4;
    let lastError = null;

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const response = UrlFetchApp.fetch(url, {
        method: 'post',
        contentType: 'application/json',
        muteHttpExceptions: true,
        headers: {
          Authorization: 'Bearer ' + apiKey,
        },
        payload: JSON.stringify(payload),
      });

      const code = response.getResponseCode();
      const text = response.getContentText();
      if (code >= 200 && code < 300) {
        return JSON.parse(text);
      }

      lastError = new Error('OpenAI call failed with ' + code + ': ' + text);
      if (code === 429 || code >= 500) {
        Utilities.sleep(Math.min(1000 * Math.pow(2, attempt - 1), 8000));
        continue;
      }
      throw lastError;
    }

    throw lastError || new Error('OpenAI call failed without a response.');
  }

  function extractStructuredOutput_(response) {
    if (!response) {
      throw new Error('Empty AI response.');
    }
    if (response.output_parsed) {
      return response.output_parsed;
    }
    if (response.output_text) {
      return parseMaybeJson_(response.output_text);
    }
    if (Array.isArray(response.output)) {
      for (let i = 0; i < response.output.length; i += 1) {
        const item = response.output[i];
        if (item.parsed) {
          return item.parsed;
        }
        if (Array.isArray(item.content)) {
          for (let j = 0; j < item.content.length; j += 1) {
            const part = item.content[j];
            if (part.parsed) {
              return part.parsed;
            }
            if (part.json) {
              return part.json;
            }
            if (part.text) {
              const candidate = parseMaybeJson_(part.text);
              if (candidate) {
                return candidate;
              }
            }
          }
        }
      }
    }
    throw new Error('Unable to parse structured AI output: ' + Utils.truncate(JSON.stringify(response), 2000));
  }

  function parseMaybeJson_(value) {
    if (!value) {
      return null;
    }
    if (typeof value === 'object') {
      return value;
    }
    const parsed = Utils.parseJson(value, null);
    if (!parsed) {
      throw new Error('Expected JSON structured output but received: ' + Utils.truncate(String(value), 1000));
    }
    return parsed;
  }

  return {
    generateStructuredJson,
  };
})();
