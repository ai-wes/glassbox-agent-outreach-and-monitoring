function sidebarGetStatus() {
  return {
    queue: JobQueue.getQueueSummary(),
    runtime: ConfigService.describeRuntime(),
    automation: AutomationService.getStatus(),
    platform: PlatformSyncService.getPlatformStatusSafe(),
  };
}

function sidebarGetSelection() {
  try {
    const selection = SelectionService.getSelectedContext();
    return {
      ok: true,
      selection: selection,
    };
  } catch (error) {
    return {
      ok: false,
      error: Utils.stringifyError(error),
    };
  }
}

function sidebarRunAction(action) {
  switch (action) {
    case 'setup':
      return SetupService.setupProject();
    case 'processQueue':
      return { processed: JobQueue.processPendingJobs() };
    case 'refreshPlatform':
      return PlatformSyncService.refreshPlatformViews();
    case 'pauseAutomation':
      return AutomationService.pause();
    case 'resumeAutomation':
      return AutomationService.resume();
    case 'maintenance':
      runHourlyMaintenance();
      return { ok: true };
    case 'digest':
      return DigestService.sendDailyDigests();
    case 'leadScore': {
      const selection = SelectionService.getSelectedContext();
      if (selection.entityType !== 'lead') {
        throw new Error('Select a row in the Leads sheet.');
      }
      LeadService.enqueueLeadScoreIfChanged(selection.entityId);
      return { ok: true, entityId: selection.entityId };
    }
    case 'accountBrief': {
      const selection = SelectionService.getSelectedContext();
      if (selection.entityType !== 'account') {
        throw new Error('Select a row in the Accounts sheet.');
      }
      AccountService.enqueueAccountBriefIfChanged(selection.entityId);
      return { ok: true, entityId: selection.entityId };
    }
    case 'followupDraft': {
      const selection = SelectionService.getSelectedContext();
      if (['lead', 'deal'].indexOf(selection.entityType) === -1) {
        throw new Error('Select a row in the Leads or Deals sheet.');
      }
      DraftService.enqueueFollowupDraft(selection.entityType, selection.entityId);
      return { ok: true, entityId: selection.entityId };
    }
    case 'gmailDraft': {
      const selection = SelectionService.getSelectedContext();
      if (['lead', 'deal'].indexOf(selection.entityType) === -1) {
        throw new Error('Select a row in the Leads or Deals sheet.');
      }
      return DraftService.createDraftFromLatestOutput(selection.entityType, selection.entityId);
    }
    default:
      throw new Error('Unknown sidebar action: ' + action);
  }
}
