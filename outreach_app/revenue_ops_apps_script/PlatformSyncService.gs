const PlatformSyncService = (() => {
  function refreshPlatformViews() {
    const cfg = ConfigService.getOutreachApiConfig();
    const bundle = PlatformApi.fetchBundle(cfg.syncLimit);
    const updatedAt = Utils.nowIso();

    const dashboardRows = buildDashboardRows_(bundle.status, updatedAt);
    const prEventRows = buildPrEventRows_(bundle.prEvents);
    const radarRows = buildRadarOpportunityRows_(bundle.radarOpportunities);

    replaceSheetData_('Dashboard', dashboardRows);
    replaceSheetData_('PR_Events', prEventRows);
    replaceSheetData_('Radar_Opportunities', radarRows);

    const result = {
      updatedAt: updatedAt,
      dashboardRows: dashboardRows.length,
      prEvents: prEventRows.length,
      radarOpportunities: radarRows.length,
      warnings: countWarnings_(bundle.status),
      baseUrl: cfg.baseUrl,
    };

    LogService.info('PlatformSyncService.refreshPlatformViews', {
      message: 'Platform views refreshed.',
      entityType: 'platform',
      entityId: 'dashboard',
      responseCode: 200,
    });
    return result;
  }

  function getPlatformStatusSafe() {
    try {
      return {
        ok: true,
        status: PlatformApi.fetchStatus(),
      };
    } catch (error) {
      return {
        ok: false,
        error: Utils.stringifyError(error),
      };
    }
  }

  function buildDashboardRows_(status, updatedAt) {
    const rows = [];
    pushObjectRows_(rows, 'crm_summary', status.crm && status.crm.summary, updatedAt);
    pushObjectRows_(rows, 'crm_funnel', status.crm && status.crm.funnel, updatedAt);
    pushObjectRows_(rows, 'pr_counts', status.pr && status.pr.counts, updatedAt);
    pushObjectRows_(rows, 'radar_counts', status.radar && status.radar.counts, updatedAt);

    if (status.pr) {
      rows.push(makeRow_(
        'pr_database_path',
        'pr_status',
        'database_path',
        status.pr.database_path || '',
        status.pr.database_url || '',
        updatedAt
      ));
      rows.push(makeRow_(
        'pr_sqlite_journal_present',
        'pr_status',
        'sqlite_journal_present',
        status.pr.sqlite_journal_present,
        '',
        updatedAt
      ));
      const latestReport = status.pr.latest_daily_podcast_report || null;
      if (latestReport) {
        rows.push(makeRow_(
          'pr_latest_daily_podcast_report',
          'pr_status',
          'latest_daily_podcast_report',
          latestReport.status || '',
          Utils.limitCellText(Utils.stableStringify(latestReport)),
          updatedAt
        ));
      }
      pushWarningRows_(rows, 'pr_warning', status.pr.warnings, updatedAt);
    }

    if (status.radar) {
      rows.push(makeRow_(
        'radar_watchlist_path',
        'radar_status',
        'watchlist_path',
        status.radar.watchlist_path || '',
        '',
        updatedAt
      ));
      rows.push(makeRow_(
        'radar_watchlist_companies',
        'radar_status',
        'watchlist_companies',
        status.radar.watchlist_companies,
        '',
        updatedAt
      ));
      rows.push(makeRow_(
        'radar_sheet_export_ready',
        'radar_status',
        'sheet_export_ready',
        status.radar.sheet_export_ready,
        '',
        updatedAt
      ));
      pushWarningRows_(rows, 'radar_warning', status.radar.warnings, updatedAt);
    }

    if (status.generated_at) {
      rows.push(makeRow_(
        'platform_generated_at',
        'platform',
        'generated_at',
        status.generated_at,
        '',
        updatedAt
      ));
    }

    return rows;
  }

  function buildPrEventRows_(items) {
    return Utils.ensureArray(items).map((item) => ({
      event_id: item.event_id || '',
      published_at: item.published_at || '',
      created_at: item.created_at || '',
      source_type: item.source_type || '',
      title: item.title || '',
      author: item.author || '',
      url: item.url || '',
      sentiment: item.sentiment === undefined || item.sentiment === null ? '' : item.sentiment,
      detected_entities: Utils.ensureArray(item.detected_entities).join(', '),
      raw_text_excerpt: item.raw_text_excerpt || '',
    }));
  }

  function buildRadarOpportunityRows_(items) {
    return Utils.ensureArray(items).map((item) => ({
      opportunity_id: item.opportunity_id || '',
      company_id: item.company_id || '',
      company_name: item.company_name || '',
      program_id: item.program_id || '',
      program_target: item.program_target || '',
      asset_name: item.asset_name || '',
      indication: item.indication || '',
      stage: item.stage || '',
      status: item.status || '',
      tier: item.tier || '',
      radar_score: item.radar_score === undefined || item.radar_score === null ? '' : item.radar_score,
      outreach_angle: item.outreach_angle || '',
      risk_hypothesis: item.risk_hypothesis || '',
      updated_at: item.updated_at || '',
      dossier_path: item.dossier_path || '',
      sheet_row_reference: item.sheet_row_reference || '',
    }));
  }

  function replaceSheetData_(sheetName, records) {
    Repository.ensureHeaders(sheetName);
    Repository.clearData(sheetName);
    if (records.length) {
      Repository.append(sheetName, records);
    }
  }

  function pushObjectRows_(rows, section, obj, updatedAt) {
    const source = obj || {};
    Object.keys(source).sort().forEach((key) => {
      rows.push(makeRow_(
        section + ':' + key,
        section,
        key,
        source[key],
        '',
        updatedAt
      ));
    });
  }

  function pushWarningRows_(rows, section, warnings, updatedAt) {
    Utils.ensureArray(warnings).forEach((warning, index) => {
      rows.push(makeRow_(
        section + ':' + (index + 1),
        section,
        'warning_' + (index + 1),
        warning,
        '',
        updatedAt
      ));
    });
  }

  function makeRow_(metricKey, section, metric, value, detail, updatedAt) {
    return {
      metric_key: metricKey,
      section: section,
      metric: metric,
      value: value,
      detail: detail,
      updated_at: updatedAt,
    };
  }

  function countWarnings_(status) {
    const prWarnings = Utils.ensureArray(status.pr && status.pr.warnings).length;
    const radarWarnings = Utils.ensureArray(status.radar && status.radar.warnings).length;
    return prWarnings + radarWarnings;
  }

  return {
    getPlatformStatusSafe,
    refreshPlatformViews,
  };
})();

function refreshPlatformViews() {
  return PlatformSyncService.refreshPlatformViews();
}
