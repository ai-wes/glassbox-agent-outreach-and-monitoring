const RoutingService = (() => {
  function selectOwnerForLead(lead) {
    const activeRules = Repository.filter('Routing_Rules', (rule) => Utils.parseBoolean(rule.active, false))
      .sort((a, b) => Utils.asNumber(a.priority, 9999) - Utils.asNumber(b.priority, 9999));

    for (let i = 0; i < activeRules.length; i += 1) {
      const rule = activeRules[i];
      if (!matchesRule_(lead, rule)) {
        continue;
      }
      if (rule.owner) {
        return Utils.normalizeEmail(rule.owner);
      }
      const owners = ownersForRule_(rule);
      if (owners.length) {
        return nextRoundRobinOwner_(owners, rule.round_robin_pool || 'default');
      }
    }

    const fallbackOwners = ConfigService.getRoundRobinOwners();
    if (fallbackOwners.length) {
      return nextRoundRobinOwner_(fallbackOwners, 'default');
    }
    return '';
  }

  function getKnownOwners() {
    const owners = {};
    ConfigService.getRoundRobinOwners().forEach((email) => { owners[email] = true; });
    Repository.filter('Routing_Rules', (rule) => Utils.parseBoolean(rule.active, false)).forEach((rule) => {
      if (rule.owner) {
        owners[Utils.normalizeEmail(rule.owner)] = true;
      }
      ownersForRule_(rule).forEach((email) => { owners[email] = true; });
    });
    return Object.keys(owners).filter((email) => email);
  }

  function ownersForRule_(rule) {
    const raw = Utils.nonEmptyString(rule.round_robin_pool);
    if (!raw) {
      return [];
    }
    if (raw.indexOf('@') !== -1 || raw.indexOf(',') !== -1) {
      return raw.split(',').map((item) => Utils.normalizeEmail(item)).filter((item) => item);
    }
    const namedPool = ConfigService.getString('ROUND_ROBIN_POOL_' + raw.toUpperCase(), '');
    if (namedPool) {
      return namedPool.split(',').map((item) => Utils.normalizeEmail(item)).filter((item) => item);
    }
    if (raw === 'default') {
      return ConfigService.getRoundRobinOwners();
    }
    return [];
  }

  function nextRoundRobinOwner_(owners, poolKey) {
    if (!owners.length) {
      return '';
    }
    const scriptProperties = ConfigService.getScriptProperties();
    const key = 'ROUND_ROBIN_INDEX_' + String(poolKey || 'default').toUpperCase();
    const currentIndex = Utils.asInt(scriptProperties.getProperty(key), 0) || 0;
    const owner = owners[currentIndex % owners.length];
    scriptProperties.setProperty(key, String((currentIndex + 1) % owners.length));
    return owner;
  }

  function matchesRule_(lead, rule) {
    return matchesField_(lead.source, rule.source_match) &&
      matchesField_(lead.domain, rule.domain_match) &&
      matchesField_(lead.country, rule.country_match) &&
      matchesField_(lead.tier || '', rule.company_tier);
  }

  function matchesField_(actual, expected) {
    const exp = Utils.normalizeWhitespace(expected).toLowerCase();
    if (!exp) {
      return true;
    }
    return Utils.normalizeWhitespace(actual).toLowerCase() === exp;
  }

  return {
    getKnownOwners,
    selectOwnerForLead,
  };
})();
