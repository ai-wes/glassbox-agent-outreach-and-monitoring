function smokeTestIngestLead() {
  const payload = {
    event_type: 'lead',
    source: 'website_form',
    first_name: 'Avery',
    last_name: 'Stone',
    email: 'avery.stone@example.com',
    company: 'Northwind Bio',
    title: 'VP Operations',
    country: 'US',
    message: 'We are evaluating solutions to improve pipeline visibility and reduce CRM follow-up gaps.',
    secret: ConfigService.getWebhookSecret(),
  };
  return LeadService.ingestInboundLead(payload);
}

function smokeTestMeetingTranscript() {
  const firstDeal = Repository.getAll('Deals')[0];
  if (!firstDeal) {
    throw new Error('Create at least one deal before running this test.');
  }
  return MeetingService.ingestMeetingTranscript({
    event_type: 'meeting_transcript',
    linked_entity_type: 'deal',
    linked_entity_id: firstDeal.deal_id,
    subject: 'Discovery call',
    transcript_text: 'Customer said budget is approved, but procurement may take two weeks. Next step is to send pricing by Friday.',
    participants: ['Jane Buyer', 'Alex Rep'],
    secret: ConfigService.getWebhookSecret(),
  });
}

function smokeTestProcessQueue() {
  return JobQueue.processPendingJobs();
}

function smokeTestPlatformSync() {
  return PlatformSyncService.refreshPlatformViews();
}
