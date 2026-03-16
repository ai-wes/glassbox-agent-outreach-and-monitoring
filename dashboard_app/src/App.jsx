import { useEffect, useMemo, useState } from "react";
import OnboardingPanel from "./OnboardingPanel";

const OUTREACH_BASE = "/api/outreach";
const MONITOR_BASE = "/api/monitor";
const STORAGE_KEY = "glassbox-dashboard-agent-api-key";

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    throw new Error(
      typeof data === "string" ? data : data.detail || "Request failed",
    );
  }
  return data;
}

function authHeaders(apiKey) {
  return { "X-API-Key": apiKey };
}

function formatTimestamp(value) {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "0";
  }
  if (typeof value !== "number") {
    return String(value);
  }
  return value.toLocaleString();
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "0%";
  }
  return `${Number(value).toFixed(1)}%`;
}

function statusTone(value) {
  const normalized = String(value || "").toLowerCase();
  if (
    normalized.includes("paused") ||
    normalized.includes("warning") ||
    normalized.includes("idle")
  ) {
    return "amber";
  }
  if (
    normalized.includes("error") ||
    normalized.includes("failed") ||
    normalized.includes("missing")
  ) {
    return "rose";
  }
  if (
    normalized.includes("running") ||
    normalized.includes("ready") ||
    normalized.includes("completed") ||
    normalized.includes("ok")
  ) {
    return "teal";
  }
  return "slate";
}

function DetailBlock({ title, hint, children, actions = null }) {
  return (
    <section className="detail-block">
      <div className="detail-head">
        <div>
          <h3>{title}</h3>
          {hint ? <span>{hint}</span> : null}
        </div>
        {actions ? <div className="detail-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

function EmptyState({ title, body }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function MetricCard({ label, value, accent = "slate", helper = null }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong className={`accent-${accent}`}>{value}</strong>
      {helper ? <p>{helper}</p> : null}
    </div>
  );
}

function StatusBadge({ label, value }) {
  return (
    <div className={`status-badge tone-${statusTone(value)}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function KeyValueList({ items }) {
  return (
    <div className="kv-grid">
      {items.map((item) => (
        <div key={item.label} className="kv-card">
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

function WarningList({ title, warnings }) {
  if (!warnings.length) {
    return (
      <div className="empty-inline">
        <strong>{title}</strong>
        <p>No active warnings.</p>
      </div>
    );
  }

  return (
    <div className="warning-group">
      <strong>{title}</strong>
      <ul className="warning-list">
        {warnings.map((warning, index) => (
          <li key={`${title}-${index}`}>{warning}</li>
        ))}
      </ul>
    </div>
  );
}

function ReportCard({
  kicker,
  title,
  body,
  metaLeft,
  metaRight,
  onClick,
  href,
}) {
  const content = (
    <>
      <span className="report-kicker">{kicker}</span>
      <strong>{title}</strong>
      <p>{body}</p>
      <div className="report-meta">
        <span>{metaLeft}</span>
        <span>{metaRight}</span>
      </div>
    </>
  );

  if (href) {
    return (
      <a className="report-card" href={href} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }

  return (
    <button type="button" className="report-card" onClick={onClick}>
      {content}
    </button>
  );
}

export default function App() {
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem(STORAGE_KEY) || "change-me-agent-key",
  );
  const [platformStatus, setPlatformStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [prEvents, setPrEvents] = useState([]);
  const [radarOpportunities, setRadarOpportunities] = useState([]);
  const [dailyReports, setDailyReports] = useState([]);
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [selectedRadarReport, setSelectedRadarReport] = useState(null);
  const [selectedDailyReport, setSelectedDailyReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [status, setStatus] = useState("Ready.");
  const [lastRefresh, setLastRefresh] = useState(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, apiKey);
  }, [apiKey]);

  async function refreshDashboard() {
    setLoading(true);
    setStatus("Refreshing platform state...");
    try {
      const headers = authHeaders(apiKey);
      const [statusData, runData, prData, radarData, dailyData, pendingData] =
        await Promise.all([
          fetchJson(`${OUTREACH_BASE}/agent/platform/status`, { headers }),
          fetchJson(`${OUTREACH_BASE}/agent/reports/runs?limit=12`, {
            headers,
          }),
          fetchJson(`${OUTREACH_BASE}/agent/platform/pr/events?limit=12`, {
            headers,
          }),
          fetchJson(
            `${OUTREACH_BASE}/agent/platform/radar/opportunities?limit=12`,
            { headers },
          ),
          fetchJson(`${OUTREACH_BASE}/agent/reports/daily-podcast?limit=8`, {
            headers,
          }),
          fetchJson(
            `${OUTREACH_BASE}/crm/gtm/messages/pending-approval?limit=12`,
            { headers },
          ),
        ]);

      setPlatformStatus(statusData);
      setRuns(runData);
      setPrEvents(prData);
      setRadarOpportunities(radarData);
      setDailyReports(dailyData);
      setPendingApprovals(pendingData);
      setLastRefresh(new Date().toLocaleString());
      setStatus("Platform state updated.");
    } catch (error) {
      setStatus(error.message || "Failed to refresh dashboard.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshDashboard();
  }, []);

  async function openRun(runId) {
    try {
      const report = await fetchJson(
        `${OUTREACH_BASE}/agent/reports/runs/${runId}`,
        {
          headers: authHeaders(apiKey),
        },
      );
      setSelectedRun(report);
      setStatus(`Loaded run ${runId}.`);
    } catch (error) {
      setStatus(error.message || `Failed loading run ${runId}.`);
    }
  }

  async function openRadarReport(opportunityId) {
    try {
      const report = await fetchJson(
        `${OUTREACH_BASE}/agent/reports/radar/opportunities/${opportunityId}?include_content=true`,
        { headers: authHeaders(apiKey) },
      );
      setSelectedRadarReport(report);
      setStatus(`Loaded radar opportunity ${opportunityId}.`);
    } catch (error) {
      setStatus(
        error.message || `Failed loading radar opportunity ${opportunityId}.`,
      );
    }
  }

  async function openDailyReport(reportId) {
    try {
      const report = await fetchJson(
        `${OUTREACH_BASE}/agent/reports/daily-podcast/${reportId}`,
        {
          headers: authHeaders(apiKey),
        },
      );
      setSelectedDailyReport(report);
      setStatus(`Loaded daily report ${reportId}.`);
    } catch (error) {
      setStatus(error.message || `Failed loading daily report ${reportId}.`);
    }
  }

  async function runCommand({ label, path, method = "POST" }) {
    setBusyAction(label);
    try {
      const payload = await fetchJson(`${OUTREACH_BASE}${path}`, {
        method,
        headers: authHeaders(apiKey),
      });
      setStatus(`${label} completed.`);
      if (path.includes("/platform/automation/")) {
        setPlatformStatus((current) => ({
          ...(current || {}),
          automation: payload,
        }));
      }
      await refreshDashboard();
    } catch (error) {
      setStatus(error.message || `${label} failed.`);
    } finally {
      setBusyAction("");
    }
  }

  async function reviewMessage(messageId, action, notes) {
    const label = action === "approve" ? "Approve email" : "Reject email";
    setBusyAction(`${action}:${messageId}`);
    try {
      await fetchJson(
        `${OUTREACH_BASE}/crm/gtm/messages/${messageId}/${action}`,
        {
          method: "POST",
          headers: {
            ...authHeaders(apiKey),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            approved_by: "dashboard",
            notes,
            send_immediately: action === "approve",
          }),
        },
      );
      setStatus(`${label} completed.`);
      await refreshDashboard();
    } catch (error) {
      setStatus(error.message || `${label} failed.`);
    } finally {
      setBusyAction("");
    }
  }

  async function downloadProtected(url, filename) {
    try {
      const response = await fetch(url, { headers: authHeaders(apiKey) });
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || "Download failed");
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(objectUrl);
      setStatus(`Downloaded ${filename}.`);
    } catch (error) {
      setStatus(error.message || `Failed downloading ${filename}.`);
    }
  }

  const automation = platformStatus?.automation || {};
  const crmSummary = platformStatus?.crm?.summary || {};
  const crmFunnel = platformStatus?.crm?.funnel || {};
  const prCounts = platformStatus?.pr?.counts || {};
  const radarCounts = platformStatus?.radar?.counts || {};

  const topMetrics = useMemo(
    () => [
      {
        label: "CRM Leads",
        value: formatNumber(crmSummary.leads_total),
        accent: "amber",
        helper: `${formatNumber(crmSummary.sent_messages)} messages sent`,
      },
      {
        label: "Positive Replies",
        value: formatNumber(crmSummary.positive_replies),
        accent: "teal",
        helper: formatPercent(crmSummary.positive_reply_rate_pct),
      },
      {
        label: "PR Events",
        value: formatNumber(prCounts.events),
        accent: "teal",
        helper: `${formatNumber(prCounts.raw_events)} raw events`,
      },
      {
        label: "Radar Opportunities",
        value: formatNumber(radarCounts.opportunities),
        accent: "amber",
        helper: `${formatNumber(radarCounts.signals)} signals`,
      },
      {
        label: "Daily Reports",
        value: formatNumber(dailyReports.length),
        accent: "rose",
        helper:
          platformStatus?.pr?.latest_daily_podcast_report?.status || "none",
      },
      {
        label: "Pending Approvals",
        value: formatNumber(pendingApprovals.length),
        accent: pendingApprovals.length ? "amber" : "slate",
        helper: pendingApprovals.length ? "manual send review queue" : "clear",
      },
      {
        label: "Queue Runner",
        value: automation.paused
          ? "Paused"
          : automation.running
            ? "Running"
            : "Idle",
        accent: automation.paused
          ? "amber"
          : automation.running
            ? "teal"
            : "slate",
        helper: automation.next_run_at
          ? `Next ${formatTimestamp(automation.next_run_at)}`
          : "No next run",
      },
    ],
    [
      automation,
      crmSummary,
      dailyReports.length,
      pendingApprovals.length,
      platformStatus?.pr?.latest_daily_podcast_report?.status,
      prCounts,
      radarCounts,
    ],
  );

  const combinedWarnings = [
    ...(platformStatus?.pr?.warnings || []).map((warning) => ({
      scope: "PR",
      warning,
    })),
    ...(platformStatus?.radar?.warnings || []).map((warning) => ({
      scope: "Radar",
      warning,
    })),
  ];

  const [activeSection, setActiveSection] = useState("dashboard");

  return (
    <div className="dashboard-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">G</div>
          <span>Glassbox</span>
        </div>

        <p className="sidebar-section-label">Main</p>
        <nav className="sidebar-nav">
          <button
            type="button"
            className={`sidebar-link${activeSection === "dashboard" ? " active" : ""}`}
            onClick={() => setActiveSection("dashboard")}
          >
            <span className="nav-icon">&#9632;</span>
            Dashboard
          </button>
          <button
            type="button"
            className={`sidebar-link${activeSection === "onboarding" ? " active" : ""}`}
            onClick={() => setActiveSection("onboarding")}
          >
            <span className="nav-icon">&#10010;</span>
            Onboarding
          </button>
          <button
            type="button"
            className={`sidebar-link${activeSection === "pr" ? " active" : ""}`}
            onClick={() => setActiveSection("pr")}
          >
            <span className="nav-icon">&#9830;</span>
            PR Events
          </button>
          <button
            type="button"
            className={`sidebar-link${activeSection === "radar" ? " active" : ""}`}
            onClick={() => setActiveSection("radar")}
          >
            <span className="nav-icon">&#9678;</span>
            Radar
          </button>
          <button
            type="button"
            className={`sidebar-link${activeSection === "approvals" ? " active" : ""}`}
            onClick={() => setActiveSection("approvals")}
          >
            <span className="nav-icon">&#9745;</span>
            Approvals
            {pendingApprovals.length > 0 && (
              <span className="badge">{pendingApprovals.length}</span>
            )}
          </button>
          <button
            type="button"
            className={`sidebar-link${activeSection === "reports" ? " active" : ""}`}
            onClick={() => setActiveSection("reports")}
          >
            <span className="nav-icon">&#9776;</span>
            Reports
          </button>
        </nav>

        <p className="sidebar-section-label">Automation</p>
        <nav className="sidebar-nav">
          <button
            type="button"
            className="sidebar-link"
            onClick={() =>
              void runCommand({
                label: "Sync Watchlist",
                path: "/radar/api/watchlist/sync",
              })
            }
            disabled={busyAction !== ""}
          >
            <span className="nav-icon">&#8635;</span>
            {busyAction === "Sync Watchlist" ? "Syncing..." : "Sync Watchlist"}
          </button>
          <button
            type="button"
            className="sidebar-link"
            onClick={() =>
              void runCommand({
                label: "Run Radar Pipeline",
                path: "/radar/api/pipeline/run",
              })
            }
            disabled={busyAction !== ""}
          >
            <span className="nav-icon">&#9654;</span>
            {busyAction === "Run Radar Pipeline"
              ? "Running..."
              : "Run Radar Pipeline"}
          </button>
          <button
            type="button"
            className="sidebar-link"
            onClick={() =>
              void runCommand({
                label: "Run Due Sequences",
                path: "/agent/crm/sequences/run-due",
              })
            }
            disabled={busyAction !== ""}
          >
            <span className="nav-icon">&#9881;</span>
            {busyAction === "Run Due Sequences"
              ? "Running..."
              : "Run Due Sequences"}
          </button>
        </nav>

        <div className="sidebar-spacer" />

        <div className="sidebar-footer">
          <p>{status}</p>
          <p style={{ marginTop: 4 }}>Last refresh: {lastRefresh || "never"}</p>
        </div>
      </aside>

      <main className="main-content">
        <div className="topbar">
          <div className="topbar-left">
            <h1>
              {activeSection === "dashboard" && "Dashboard"}
              {activeSection === "onboarding" && "AI-Assisted Client Setup"}
              {activeSection === "pr" && "PR Event Feed"}
              {activeSection === "radar" && "Radar Opportunities"}
              {activeSection === "approvals" && "Email Approvals"}
              {activeSection === "reports" && "Reports"}
            </h1>
            <p>
              CRM execution, PR indexing, radar monitoring &amp; scheduler state
            </p>
          </div>
          <div className="topbar-right">
            <button
              type="button"
              className="btn-primary"
              onClick={() => void refreshDashboard()}
              disabled={loading}
            >
              {loading ? "Refreshing..." : "Refresh"}
            </button>
            <button
              type="button"
              className="btn-outline"
              onClick={() =>
                void runCommand({
                  label: "Pause automation",
                  path: "/agent/platform/automation/pause",
                })
              }
              disabled={busyAction !== ""}
            >
              {busyAction === "Pause automation" ? "Pausing..." : "⏸ Pause"}
            </button>
            <button
              type="button"
              className="btn-outline"
              onClick={() =>
                void runCommand({
                  label: "Resume automation",
                  path: "/agent/platform/automation/resume",
                })
              }
              disabled={busyAction !== ""}
            >
              {busyAction === "Resume automation" ? "Resuming..." : "▶ Resume"}
            </button>
          </div>
        </div>

        <div className="controls-bar">
          <label className="field">
            <span>API Key</span>
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="change-me-agent-key"
            />
          </label>
          <div className="controls-divider" />
          <div className="status-row">
            <StatusBadge
              label="Automation"
              value={
                automation.paused
                  ? "paused"
                  : automation.running
                    ? "running"
                    : "idle"
              }
            />
            <StatusBadge
              label="PR"
              value={prCounts.events ? "indexed" : "empty"}
            />
            <StatusBadge
              label="Radar"
              value={radarCounts.opportunities ? "active" : "empty"}
            />
            <StatusBadge
              label="Email Gate"
              value={pendingApprovals.length ? "approval required" : "clear"}
            />
          </div>
        </div>

        {activeSection === "dashboard" && (
          <>
            <section className="metric-grid">
              {topMetrics.map((metric) => (
                <MetricCard
                  key={metric.label}
                  label={metric.label}
                  value={metric.value}
                  accent={metric.accent}
                  helper={metric.helper}
                />
              ))}
            </section>

            <section className="content-grid">
              <div className="column">
                <DetailBlock title="Platform Snapshot">
                  <KeyValueList
                    items={[
                      {
                        label: "Queued Leads",
                        value: formatNumber(crmFunnel.queued_leads),
                      },
                      {
                        label: "Sent Leads",
                        value: formatNumber(crmFunnel.sent_leads),
                      },
                      {
                        label: "Meetings",
                        value: formatNumber(crmFunnel.meetings_booked),
                      },
                      {
                        label: "PR Sources",
                        value: formatNumber(prCounts.sources),
                      },
                      {
                        label: "PR Clients",
                        value: formatNumber(prCounts.clients),
                      },
                      {
                        label: "Radar Companies",
                        value: formatNumber(radarCounts.companies),
                      },
                      {
                        label: "Radar Programs",
                        value: formatNumber(radarCounts.programs),
                      },
                      {
                        label: "Pipeline Runs",
                        value: formatNumber(radarCounts.pipeline_runs),
                      },
                    ]}
                  />
                  <div className="warning-stack">
                    <WarningList
                      title="Platform Warnings"
                      warnings={combinedWarnings.map(
                        (item) => `${item.scope}: ${item.warning}`,
                      )}
                    />
                  </div>
                </DetailBlock>
              </div>

              <div className="column">
                <DetailBlock title="Recent PR Events">
                  {prEvents.length === 0 ? (
                    <EmptyState
                      title="No PR events"
                      body="The PR ingestion plane is empty."
                    />
                  ) : (
                    <div className="report-list">
                      {prEvents.slice(0, 5).map((event) => (
                        <ReportCard
                          key={event.event_id}
                          kicker={event.source_type}
                          title={event.title}
                          body={event.raw_text_excerpt || "No text excerpt."}
                          metaLeft={event.author || "Unknown author"}
                          metaRight={formatTimestamp(event.published_at)}
                          href={event.url}
                        />
                      ))}
                    </div>
                  )}
                </DetailBlock>
              </div>

              <div className="column">
                <DetailBlock title="Top Radar Opportunities">
                  {radarOpportunities.length === 0 ? (
                    <EmptyState
                      title="No opportunities"
                      body="No scored companies or programs yet."
                    />
                  ) : (
                    <div className="report-list">
                      {radarOpportunities.slice(0, 5).map((opportunity) => (
                        <ReportCard
                          key={opportunity.opportunity_id}
                          kicker={opportunity.tier || "tier ?"}
                          title={opportunity.company_name}
                          body={
                            opportunity.asset_name ||
                            opportunity.program_target ||
                            "Unnamed program"
                          }
                          metaLeft={opportunity.status}
                          metaRight={formatNumber(opportunity.radar_score)}
                          onClick={() => {
                            setActiveSection("radar");
                            void openRadarReport(opportunity.opportunity_id);
                          }}
                        />
                      ))}
                    </div>
                  )}
                </DetailBlock>
              </div>
            </section>
          </>
        )}

        {activeSection === "onboarding" && (
          <OnboardingPanel baseUrl={MONITOR_BASE} onStatus={setStatus} />
        )}

        {activeSection === "pr" && (
          <section
            className="content-grid"
            style={{ gridTemplateColumns: "1fr 1fr" }}
          >
            <div className="column">
              <DetailBlock title="PR Event Feed">
                {prEvents.length === 0 ? (
                  <EmptyState
                    title="No PR events"
                    body="The PR ingestion plane is empty or has not been refreshed."
                  />
                ) : (
                  <div className="report-list">
                    {prEvents.map((event) => (
                      <ReportCard
                        key={event.event_id}
                        kicker={event.source_type}
                        title={event.title}
                        body={event.raw_text_excerpt || "No text excerpt."}
                        metaLeft={event.author || "Unknown author"}
                        metaRight={formatTimestamp(event.published_at)}
                        href={event.url}
                      />
                    ))}
                  </div>
                )}
              </DetailBlock>
            </div>
            <div className="column">
              <DetailBlock title="Daily Podcast Reports">
                {dailyReports.length === 0 ? (
                  <EmptyState
                    title="No daily reports"
                    body="Podcast automation has not stored report markdown yet."
                  />
                ) : (
                  <div className="report-list">
                    {dailyReports.map((report) => (
                      <ReportCard
                        key={report.id}
                        kicker={report.report_date || "No date"}
                        title={report.title}
                        body={report.summary_excerpt || "No summary excerpt."}
                        metaLeft={report.status}
                        metaRight={formatTimestamp(report.created_at)}
                        onClick={() => void openDailyReport(report.id)}
                      />
                    ))}
                  </div>
                )}
              </DetailBlock>

              <DetailBlock
                title="Daily Report Markdown"
                hint={selectedDailyReport?.id || "select a briefing"}
              >
                {!selectedDailyReport ? (
                  <EmptyState
                    title="No briefing selected"
                    body="Pick a daily report to inspect the stored markdown."
                  />
                ) : (
                  <div className="detail-stack">
                    <pre>
                      {JSON.stringify(
                        {
                          meta: selectedDailyReport.meta,
                          error_message: selectedDailyReport.error_message,
                        },
                        null,
                        2,
                      )}
                    </pre>
                    <pre className="markdown-block">
                      {selectedDailyReport.report_md ||
                        "No markdown content available."}
                    </pre>
                  </div>
                )}
              </DetailBlock>
            </div>
          </section>
        )}

        {activeSection === "radar" && (
          <section
            className="content-grid"
            style={{ gridTemplateColumns: "1fr 1fr" }}
          >
            <div className="column">
              <DetailBlock title="Radar Opportunities">
                {radarOpportunities.length === 0 ? (
                  <EmptyState
                    title="No radar opportunities"
                    body="The radar plane has not scored any companies or programs yet."
                  />
                ) : (
                  <div className="report-list">
                    {radarOpportunities.map((opportunity) => (
                      <ReportCard
                        key={opportunity.opportunity_id}
                        kicker={opportunity.tier || "tier ?"}
                        title={opportunity.company_name}
                        body={
                          opportunity.asset_name ||
                          opportunity.program_target ||
                          "Unnamed program"
                        }
                        metaLeft={opportunity.status}
                        metaRight={formatNumber(opportunity.radar_score)}
                        onClick={() =>
                          void openRadarReport(opportunity.opportunity_id)
                        }
                      />
                    ))}
                  </div>
                )}
              </DetailBlock>
            </div>
            <div className="column">
              <DetailBlock
                title="Radar Detail"
                hint={selectedRadarReport?.opportunity_id || "select a dossier"}
                actions={
                  selectedRadarReport?.report?.dossier_path ? (
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() =>
                        void downloadProtected(
                          `${OUTREACH_BASE}/agent/reports/radar/opportunities/${selectedRadarReport.opportunity_id}/download`,
                          `${selectedRadarReport.opportunity_id}.md`,
                        )
                      }
                    >
                      Download Dossier
                    </button>
                  ) : null
                }
              >
                {!selectedRadarReport ? (
                  <EmptyState
                    title="No radar report selected"
                    body="Pick an opportunity to inspect the dossier and score breakdown."
                  />
                ) : (
                  <div className="detail-stack">
                    <pre>
                      {JSON.stringify(
                        selectedRadarReport.report || {},
                        null,
                        2,
                      )}
                    </pre>
                    <pre className="markdown-block">
                      {selectedRadarReport.report?.dossier_markdown ||
                        "No dossier markdown available."}
                    </pre>
                  </div>
                )}
              </DetailBlock>
            </div>
          </section>
        )}

        {activeSection === "approvals" && (
          <section>
            <DetailBlock title="Email Approval Queue">
              {pendingApprovals.length === 0 ? (
                <EmptyState
                  title="No emails awaiting review"
                  body="Queued outbound emails will stop here before send. Approve or reject them from this panel."
                />
              ) : (
                <div className="report-list">
                  {pendingApprovals.map((message) => (
                    <div key={message.id} className="approval-card">
                      <div className="approval-copy">
                        <span className="report-kicker">{message.channel}</span>
                        <strong>
                          {message.subject || "Untitled outbound email"}
                        </strong>
                        <p>{message.body || "No message body available."}</p>
                        <div className="report-meta">
                          <span>{message.status}</span>
                          <span>{formatTimestamp(message.scheduled_for)}</span>
                        </div>
                      </div>
                      <div className="approval-actions">
                        <button
                          type="button"
                          className="btn-primary"
                          onClick={() =>
                            void reviewMessage(
                              message.id,
                              "approve",
                              "approved from dashboard",
                            )
                          }
                          disabled={busyAction !== ""}
                        >
                          {busyAction === `approve:${message.id}`
                            ? "Approving..."
                            : "Approve & Send"}
                        </button>
                        <button
                          type="button"
                          className="btn-outline"
                          onClick={() =>
                            void reviewMessage(
                              message.id,
                              "reject",
                              "rejected from dashboard",
                            )
                          }
                          disabled={busyAction !== ""}
                        >
                          {busyAction === `reject:${message.id}`
                            ? "Rejecting..."
                            : "Reject"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </DetailBlock>
          </section>
        )}

        {activeSection === "reports" && (
          <section
            className="content-grid"
            style={{ gridTemplateColumns: "1fr 1fr" }}
          >
            <div className="column">
              <DetailBlock title="Outreach Run Reports">
                {runs.length === 0 ? (
                  <EmptyState
                    title="No outreach runs yet"
                    body="The CRM execution layer has not stored agent run reports yet."
                  />
                ) : (
                  <div className="report-list">
                    {runs.map((run) => (
                      <ReportCard
                        key={run.run_id}
                        kicker={run.agent}
                        title={run.title}
                        body={run.summary || "No summary yet."}
                        metaLeft={run.status}
                        metaRight={`${run.artifact_count} artifacts`}
                        onClick={() => void openRun(run.run_id)}
                      />
                    ))}
                  </div>
                )}
              </DetailBlock>
            </div>
            <div className="column">
              <DetailBlock
                title="Run Detail"
                hint={selectedRun?.run?.id || "select a run"}
                actions={
                  selectedRun?.run?.id ? (
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() =>
                        void downloadProtected(
                          `${OUTREACH_BASE}/agent/reports/runs/${selectedRun.run.id}/download`,
                          `agent_report_${selectedRun.run.id}.zip`,
                        )
                      }
                    >
                      Download Evidence Zip
                    </button>
                  ) : null
                }
              >
                {!selectedRun ? (
                  <EmptyState
                    title="No run selected"
                    body="Choose an outreach run to inspect manifest, tool calls, and evidence."
                  />
                ) : (
                  <div className="detail-stack">
                    <pre>{JSON.stringify(selectedRun.run || {}, null, 2)}</pre>
                    <pre>
                      {JSON.stringify(selectedRun.manifest || {}, null, 2)}
                    </pre>
                    <pre>
                      {JSON.stringify(
                        (selectedRun.tool_calls || []).slice(-8),
                        null,
                        2,
                      )}
                    </pre>
                  </div>
                )}
              </DetailBlock>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
