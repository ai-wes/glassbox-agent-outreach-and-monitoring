function handleInstallableEdit(e) {
  ValidationService.handleEditEvent(e);
}

function processPendingJobs() {
  if (!AutomationService.shouldRun('processPendingJobs')) {
    return 0;
  }
  return JobQueue.processPendingJobs();
}

function runHourlyMaintenance() {
  if (!AutomationService.shouldRun('runHourlyMaintenance')) {
    return;
  }
  const staleDeals = DealService.runStaleDealAudit();
  const overdueLeads = LeadService.runFollowupReminderScan();
  let platformSync = null;
  if (ConfigService.getBoolean('ENABLE_PLATFORM_SYNC', true)) {
    try {
      platformSync = PlatformSyncService.refreshPlatformViews();
    } catch (error) {
      LogService.error('runHourlyMaintenance.platformSync', error, {
        message: 'Platform sync failed during hourly maintenance.',
      });
    }
  }
  LogService.info('runHourlyMaintenance', {
    message: 'Maintenance completed. staleDeals=' + staleDeals +
      ', overdueLeads=' + overdueLeads +
      ', platformSync=' + (platformSync ? 'ok' : 'skipped_or_failed'),
  });
}

function sendDailyDigests() {
  if (!AutomationService.shouldRun('sendDailyDigests')) {
    return { repDigests: 0, managerDigests: 0, skipped: true };
  }
  return DigestService.sendDailyDigests();
}
