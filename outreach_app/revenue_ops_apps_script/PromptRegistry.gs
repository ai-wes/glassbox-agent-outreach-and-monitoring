const PromptRegistry = (() => {
  let cache = null;

  function invalidate() {
    cache = null;
  }

  function getPromptRows_() {
    if (cache) {
      return cache.slice();
    }
    const rows = Repository.getAll('Prompt_Library');
    cache = rows.slice();
    return rows;
  }

  function getActivePrompt(promptKey) {
    const matching = getPromptRows_().filter((row) => row.prompt_key === promptKey && Utils.parseBoolean(row.active, false));
    if (!matching.length) {
      throw new Error('No active prompt found for key: ' + promptKey);
    }
    matching.sort((a, b) => compareVersions_(b.version, a.version));
    return matching[0];
  }

  function renderPrompt(promptKey, variables) {
    const prompt = getActivePrompt(promptKey);
    return {
      promptKey: prompt.prompt_key,
      version: prompt.version,
      systemText: Utils.renderTemplate(prompt.system_text, variables || {}),
      userText: Utils.renderTemplate(prompt.user_text, variables || {}),
      inputSchemaVersion: prompt.input_schema_version,
      outputSchemaVersion: prompt.output_schema_version,
    };
  }

  function reseedDefaults() {
    DataModel.DEFAULT_PROMPTS.forEach((prompt) => {
      const existing = Repository.filter('Prompt_Library', (row) => {
        return row.prompt_key === prompt.prompt_key && row.version === prompt.version;
      })[0];
      if (existing) {
        Repository.updateRow('Prompt_Library', existing.__rowNumber, prompt);
      } else {
        Repository.append('Prompt_Library', [prompt]);
      }
    });
    invalidate();
  }

  function compareVersions_(left, right) {
    const leftParts = String(left || '0').split('.').map((part) => Utils.asInt(part, 0));
    const rightParts = String(right || '0').split('.').map((part) => Utils.asInt(part, 0));
    const maxLength = Math.max(leftParts.length, rightParts.length);
    for (let i = 0; i < maxLength; i += 1) {
      const l = leftParts[i] || 0;
      const r = rightParts[i] || 0;
      if (l !== r) {
        return l - r;
      }
    }
    return 0;
  }

  return {
    getActivePrompt,
    invalidate,
    renderPrompt,
    reseedDefaults,
  };
})();
