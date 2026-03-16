function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Revenue Ops')
    .addItem('Setup / Repair Workbook', 'setupProjectMenu')
    .addItem('Open Command Center', 'showRevenueOpsSidebar')
    .addItem('Refresh Platform Views', 'refreshPlatformViewsNow')
    .addSeparator()
    .addItem('Process AI Queue Now', 'processQueueNow')
    .addItem('Run Hourly Maintenance Now', 'runHourlyMaintenanceNow')
    .addItem('Send Daily Digests Now', 'sendDailyDigestsNow')
    .addSeparator()
    .addItem('Score Selected Lead', 'scoreSelectedLead')
    .addItem('Generate Selected Account Brief', 'generateSelectedAccountBrief')
    .addItem('Generate Selected Follow-Up Draft', 'generateSelectedFollowupDraft')
    .addItem('Create Gmail Draft for Selected Record', 'createSelectedGmailDraft')
    .addToUi();
}

function setupProjectMenu() {
  const result = SetupService.setupProject();
  SpreadsheetApp.getUi().alert(
    'Revenue Ops setup complete.\n\nSpreadsheet ID: ' + result.spreadsheetId +
    '\nWebhook secret created in Script Properties.'
  );
}

function showRevenueOpsSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setTitle('Revenue Ops Command Center');
  SpreadsheetApp.getUi().showSidebar(html);
}

function processQueueNow() {
  const processed = JobQueue.processPendingJobs();
  Utils.tryToast('Processed ' + processed + ' job(s).');
}

function refreshPlatformViewsNow() {
  const result = PlatformSyncService.refreshPlatformViews();
  Utils.tryToast(
    'Platform views refreshed. PR events: ' + result.prEvents +
    ' | Radar opps: ' + result.radarOpportunities,
    'Revenue Ops'
  );
}

function runHourlyMaintenanceNow() {
  runHourlyMaintenance();
  Utils.tryToast('Hourly maintenance completed.');
}

function sendDailyDigestsNow() {
  const result = DigestService.sendDailyDigests();
  Utils.tryToast('Rep digests: ' + result.repDigests + ' | Manager digests: ' + result.managerDigests);
}

function scoreSelectedLead() {
  const selection = SelectionService.getSelectedContext();
  if (selection.entityType !== 'lead') {
    throw new Error('Select a row in the Leads sheet.');
  }
  LeadService.enqueueLeadScoreIfChanged(selection.entityId);
  Utils.tryToast('Lead scoring job queued.');
}

function generateSelectedAccountBrief() {
  const selection = SelectionService.getSelectedContext();
  if (selection.entityType !== 'account') {
    throw new Error('Select a row in the Accounts sheet.');
  }
  AccountService.enqueueAccountBriefIfChanged(selection.entityId);
  Utils.tryToast('Account brief job queued.');
}

function generateSelectedFollowupDraft() {
  const selection = SelectionService.getSelectedContext();
  if (['lead', 'deal'].indexOf(selection.entityType) === -1) {
    throw new Error('Select a row in the Leads or Deals sheet.');
  }
  DraftService.enqueueFollowupDraft(selection.entityType, selection.entityId);
  Utils.tryToast('Follow-up draft job queued.');
}

function createSelectedGmailDraft() {
  const selection = SelectionService.getSelectedContext();
  if (['lead', 'deal'].indexOf(selection.entityType) === -1) {
    throw new Error('Select a row in the Leads or Deals sheet.');
  }
  const result = DraftService.createDraftFromLatestOutput(selection.entityType, selection.entityId);
  SpreadsheetApp.getUi().alert('Draft created for ' + result.recipient + '\nSubject: ' + result.subject);
}
