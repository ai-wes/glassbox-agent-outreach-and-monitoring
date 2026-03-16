const DigestService = (() => {
  function sendDailyDigests() {
    const sent = {
      repDigests: 0,
      managerDigests: 0,
    };

    if (ConfigService.getBoolean('ENABLE_REP_DIGEST', true)) {
      RoutingService.getKnownOwners().forEach((owner) => {
        if (sendRepDigest_(owner)) {
          sent.repDigests += 1;
        }
      });
    }

    if (ConfigService.getBoolean('ENABLE_MANAGER_DIGEST', true)) {
      const recipients = ConfigService.getManagerDigestRecipients();
      if (recipients.length && sendManagerDigest_(recipients)) {
        sent.managerDigests += recipients.length;
      }
    }

    return sent;
  }

  function sendRepDigest_(owner) {
    const highPriorityLeads = Repository.filter('Leads', (lead) => {
      return String(lead.owner || '') === owner &&
        ['new', 'working', 'qualified', 'nurture'].indexOf(String(lead.status || '')) !== -1 &&
        Utils.asInt(lead.priority_score, 0) >= ConfigService.getNumber('LEAD_REVIEW_THRESHOLD', 70);
    }).sort((a, b) => Utils.asInt(b.priority_score, 0) - Utils.asInt(a.priority_score, 0)).slice(0, 10);

    const overdueTasks = Repository.filter('Tasks', (task) => {
      const due = Utils.toDate(task.due_at);
      return task.status === 'open' &&
        String(task.owner || '') === owner &&
        (!due || due.getTime() <= new Date().getTime());
    }).slice(0, 10);

    const riskyDeals = Repository.filter('Deals', (deal) => {
      return String(deal.owner || '') === owner &&
        ['closed_won', 'closed_lost'].indexOf(String(deal.stage || '')) === -1 &&
        (Utils.parseBoolean(deal.needs_review, false) || Utils.asInt(deal.risk_score, 0) >= 70);
    }).sort((a, b) => Utils.asInt(b.risk_score, 0) - Utils.asInt(a.risk_score, 0)).slice(0, 10);

    if (!highPriorityLeads.length && !overdueTasks.length && !riskyDeals.length) {
      return false;
    }

    const subject = 'Daily revenue ops digest';
    const htmlBody = [
      '<h2>Daily revenue ops digest</h2>',
      '<p><strong>Owner:</strong> ' + Utils.htmlEscape(owner) + '</p>',
      renderLeadsTable_(highPriorityLeads, 'High-priority leads'),
      renderTasksTable_(overdueTasks, 'Overdue tasks'),
      renderDealsTable_(riskyDeals, 'Risky deals'),
    ].join('');

    MailApp.sendEmail({
      to: owner,
      subject: subject,
      htmlBody: htmlBody,
      body: stripHtml_(htmlBody),
    });

    return true;
  }

  function sendManagerDigest_(recipients) {
    const hotLeads = Repository.filter('Leads', (lead) => Utils.asInt(lead.priority_score, 0) >= ConfigService.getNumber('HIGH_PRIORITY_THRESHOLD', 85))
      .sort((a, b) => Utils.asInt(b.priority_score, 0) - Utils.asInt(a.priority_score, 0))
      .slice(0, 15);

    const riskyDeals = Repository.filter('Deals', (deal) => Utils.asInt(deal.risk_score, 0) >= 75 || Utils.parseBoolean(deal.needs_review, false))
      .sort((a, b) => Utils.asInt(b.risk_score, 0) - Utils.asInt(a.risk_score, 0))
      .slice(0, 15);

    const queue = JobQueue.getQueueSummary();
    const htmlBody = [
      '<h2>Manager revenue ops digest</h2>',
      '<p><strong>Queue:</strong> ' + Utils.htmlEscape(JSON.stringify(queue)) + '</p>',
      renderLeadsTable_(hotLeads, 'Hottest leads'),
      renderDealsTable_(riskyDeals, 'Highest-risk deals'),
    ].join('');

    MailApp.sendEmail({
      to: recipients.join(','),
      subject: 'Manager revenue ops digest',
      htmlBody: htmlBody,
      body: stripHtml_(htmlBody),
    });
    return true;
  }

  function renderLeadsTable_(leads, title) {
    if (!leads.length) {
      return '<h3>' + Utils.htmlEscape(title) + '</h3><p>No items.</p>';
    }
    const rows = leads.map((lead) => {
      return '<tr>' +
        '<td>' + Utils.htmlEscape((lead.first_name || '') + ' ' + (lead.last_name || '')) + '</td>' +
        '<td>' + Utils.htmlEscape(lead.company || '') + '</td>' +
        '<td>' + Utils.htmlEscape(String(lead.priority_score || '')) + '</td>' +
        '<td>' + Utils.htmlEscape(lead.next_action || '') + '</td>' +
        '</tr>';
    }).join('');
    return '<h3>' + Utils.htmlEscape(title) + '</h3>' +
      '<table border="1" cellpadding="6" cellspacing="0"><tr><th>Lead</th><th>Company</th><th>Priority</th><th>Next action</th></tr>' +
      rows + '</table>';
  }

  function renderDealsTable_(deals, title) {
    if (!deals.length) {
      return '<h3>' + Utils.htmlEscape(title) + '</h3><p>No items.</p>';
    }
    const rows = deals.map((deal) => {
      return '<tr>' +
        '<td>' + Utils.htmlEscape(deal.deal_id || '') + '</td>' +
        '<td>' + Utils.htmlEscape(deal.stage || '') + '</td>' +
        '<td>' + Utils.htmlEscape(String(deal.risk_score || '')) + '</td>' +
        '<td>' + Utils.htmlEscape(deal.next_step || '') + '</td>' +
        '</tr>';
    }).join('');
    return '<h3>' + Utils.htmlEscape(title) + '</h3>' +
      '<table border="1" cellpadding="6" cellspacing="0"><tr><th>Deal</th><th>Stage</th><th>Risk</th><th>Next step</th></tr>' +
      rows + '</table>';
  }

  function renderTasksTable_(tasks, title) {
    if (!tasks.length) {
      return '<h3>' + Utils.htmlEscape(title) + '</h3><p>No items.</p>';
    }
    const rows = tasks.map((task) => {
      return '<tr>' +
        '<td>' + Utils.htmlEscape(task.task_type || '') + '</td>' +
        '<td>' + Utils.htmlEscape(task.entity_type || '') + '</td>' +
        '<td>' + Utils.htmlEscape(task.entity_id || '') + '</td>' +
        '<td>' + Utils.htmlEscape(task.due_at || '') + '</td>' +
        '</tr>';
    }).join('');
    return '<h3>' + Utils.htmlEscape(title) + '</h3>' +
      '<table border="1" cellpadding="6" cellspacing="0"><tr><th>Task</th><th>Entity type</th><th>Entity ID</th><th>Due</th></tr>' +
      rows + '</table>';
  }

  function stripHtml_(html) {
    return String(html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }

  return {
    sendDailyDigests,
  };
})();
