import { useEffect, useState } from "react";

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
    throw new Error(typeof data === "string" ? data : data.detail || "Request failed");
  }
  return data;
}

function DetailBlock({ title, children, hint }) {
  return (
    <section className="detail-block">
      <div className="detail-head">
        <h3>{title}</h3>
        {hint ? <span>{hint}</span> : null}
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

function MetricCard({ label, value, accent }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong className={accent ? `accent-${accent}` : ""}>{value}</strong>
    </div>
  );
}

export default function App() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem(STORAGE_KEY) || "change-me-agent-key");
  const [runs, setRuns] = useState([]);
  const [marketEvents, setMarketEvents] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [dailyReports, setDailyReports] = useState([]);
  const [selectedDailyReport, setSelectedDailyReport] = useState(null);
  const [radarReports, setRadarReports] = useState([]);
  const [selectedRadarReport, setSelectedRadarReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("Ready.");
  const [lastRefresh, setLastRefresh] = useState(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, apiKey);
  }, [apiKey]);

  async function refreshDashboard() {
    setLoading(true);
    setStatus("Refreshing report feeds...");
    try {
      const [runData, marketData, dailyData, radarData] = await Promise.all([
        fetchJson(`${OUTREACH_BASE}/agent/reports/runs`, {
          headers: { "X-API-Key": apiKey },
        }),
        fetchJson(`${MONITOR_BASE}/agent/reports/market/events?limit=12`),
        fetchJson(`${MONITOR_BASE}/agent/reports/daily-podcast`),
        fetchJson(`${MONITOR_BASE}/agent/reports/radar/opportunities`),
      ]);

      setRuns(runData);
      setMarketEvents(marketData);
      setDailyReports(dailyData);
      setRadarReports(radarData);
      setSelectedRun(runData[0] || null);
      setSelectedDailyReport(dailyData[0] || null);
      setSelectedRadarReport(radarData[0] || null);
      setLastRefresh(new Date().toLocaleString());
      setStatus("Feeds updated.");
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
      const report = await fetchJson(`${OUTREACH_BASE}/agent/reports/runs/${runId}`, {
        headers: { "X-API-Key": apiKey },
      });
      setSelectedRun(report);
      setStatus(`Loaded run ${runId}.`);
    } catch (error) {
      setStatus(error.message || `Failed loading run ${runId}.`);
    }
  }

  async function openDailyReport(reportId) {
    try {
      const report = await fetchJson(`${MONITOR_BASE}/agent/reports/daily-podcast/${reportId}`);
      setSelectedDailyReport(report);
      setStatus(`Loaded daily report ${reportId}.`);
    } catch (error) {
      setStatus(error.message || `Failed loading daily report ${reportId}.`);
    }
  }

  async function openRadarReport(opportunityId) {
    try {
      const report = await fetchJson(
        `${MONITOR_BASE}/agent/reports/radar/opportunities/${opportunityId}?include_content=true`,
      );
      setSelectedRadarReport(report);
      setStatus(`Loaded radar report ${opportunityId}.`);
    } catch (error) {
      setStatus(error.message || `Failed loading radar report ${opportunityId}.`);
    }
  }

  async function downloadProtected(url, filename, headers = {}) {
    try {
      const response = await fetch(url, { headers });
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

  const selectedRunData = selectedRun?.run ? selectedRun : null;
  const runItems = selectedRunData?.artifacts || [];
  const toolCalls = selectedRunData?.tool_calls || [];

  return (
    <main className="dashboard-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <section className="hero-panel">
        <div>
          <p className="eyebrow">Glassbox Container Group</p>
          <h1>Report Deck</h1>
          <p className="hero-copy">
            A dedicated React layer for live outreach evidence, biotech radar dossiers, and daily briefing output.
          </p>
        </div>

        <div className="control-panel">
          <label className="field">
            <span>Outreach Agent API Key</span>
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="change-me-agent-key"
            />
          </label>

          <div className="control-row">
            <button
              type="button"
              className="btn-primary"
              onClick={() => void refreshDashboard()}
              disabled={loading}
            >
              {loading ? "Refreshing..." : "Refresh Feeds"}
            </button>
            <div className="status-chip">{status}</div>
          </div>

          <div className="metric-grid">
            <MetricCard label="Outreach Reports" value={runs.length} accent="amber" />
            <MetricCard label="Market Signals" value={marketEvents.length} accent="teal" />
            <MetricCard label="Radar Reports" value={radarReports.length} accent="teal" />
            <MetricCard label="Daily Briefs" value={dailyReports.length} accent="rose" />
          </div>

          <p className="timestamp">Last refresh: {lastRefresh || "not yet"}</p>
        </div>
      </section>

      <section className="content-grid">
        <div className="column">
          <DetailBlock title="Outreach Run Reports" hint="/agent/reports/runs">
            {runs.length === 0 ? (
              <EmptyState
                title="No outreach runs yet"
                body="Once the CRM and operator workflows execute, evidence-backed run reports will appear here."
              />
            ) : (
              <div className="report-list">
                {runs.map((run) => (
                  <button key={run.run_id} className="report-card" onClick={() => void openRun(run.run_id)}>
                    <span className="report-kicker">{run.agent}</span>
                    <strong>{run.title}</strong>
                    <p>{run.summary || "No summary yet."}</p>
                    <div className="report-meta">
                      <span>{run.status}</span>
                      <span>{run.artifact_count} artifacts</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </DetailBlock>

          <DetailBlock title="Run Detail" hint={selectedRunData?.run?.id || "select a run"}>
            {!selectedRunData ? (
              <EmptyState title="No run selected" body="Choose a run report to inspect its manifest, tool calls, and artifacts." />
            ) : (
              <>
                <div className="detail-actions">
                  <button
                    type="button"
                    className="btn-outline"
                    onClick={() =>
                      void downloadProtected(
                        `${OUTREACH_BASE}/agent/reports/runs/${selectedRunData.run.id}/download`,
                        `agent_report_${selectedRunData.run.id}.zip`,
                        { "X-API-Key": apiKey },
                      )
                    }
                  >
                    Download Evidence Zip
                  </button>
                </div>

                <div className="detail-stack">
                  <pre>{JSON.stringify(selectedRunData.manifest || {}, null, 2)}</pre>
                  <pre>{JSON.stringify(toolCalls.slice(-6), null, 2)}</pre>
                  <pre>{JSON.stringify(runItems.slice(0, 8), null, 2)}</pre>
                </div>
              </>
            )}
          </DetailBlock>
        </div>

        <div className="column">
          <DetailBlock title="Market Signals" hint="/agent/reports/market/events">
            {marketEvents.length === 0 ? (
              <EmptyState
                title="No market signals yet"
                body="Bootstrap the RSS feeds and run PR ingestion plus processing to surface normalized events here."
              />
            ) : (
              <div className="report-list">
                {marketEvents.map((event) => (
                  <a
                    key={event.event_id}
                    className="report-card"
                    href={event.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span className="report-kicker">
                      {event.source_name || event.feed_category || event.source_type}
                    </span>
                    <strong>{event.title}</strong>
                    <p>{event.summary_excerpt || "No summary excerpt."}</p>
                    <div className="report-meta">
                      <span>{event.feed_category || event.source_type}</span>
                      <span>{event.published_at || "n/a"}</span>
                    </div>
                  </a>
                ))}
              </div>
            )}
          </DetailBlock>

          <DetailBlock title="Daily Podcast Reports" hint="/agent/reports/daily-podcast">
            {dailyReports.length === 0 ? (
              <EmptyState
                title="No daily podcast reports"
                body="This pane will fill as the monitoring stack generates daily briefing markdown."
              />
            ) : (
              <div className="report-list">
                {dailyReports.map((report) => (
                  <button key={report.id} className="report-card" onClick={() => void openDailyReport(report.id)}>
                    <span className="report-kicker">{report.report_date || "No date"}</span>
                    <strong>{report.title}</strong>
                    <p>{report.summary_excerpt || "No summary excerpt."}</p>
                    <div className="report-meta">
                      <span>{report.status}</span>
                      <span>{report.created_at || "n/a"}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </DetailBlock>

          <DetailBlock title="Daily Report Markdown" hint={selectedDailyReport?.id || "select a briefing"}>
            {!selectedDailyReport ? (
              <EmptyState title="No briefing selected" body="Pick a daily report to inspect the generated markdown." />
            ) : (
              <pre className="markdown-block">{selectedDailyReport.report_md || "No markdown content available."}</pre>
            )}
          </DetailBlock>
        </div>

        <div className="column">
          <DetailBlock title="Radar Dossiers" hint="/agent/reports/radar/opportunities">
            {radarReports.length === 0 ? (
              <EmptyState
                title="No radar opportunities yet"
                body="Run the radar pipeline or watchlist sync and dossiers will surface here for download and review."
              />
            ) : (
              <div className="report-list">
                {radarReports.map((report) => (
                  <button
                    key={report.opportunity_id}
                    className="report-card"
                    onClick={() => void openRadarReport(report.opportunity_id)}
                  >
                    <span className="report-kicker">{report.tier || "tier ?"}</span>
                    <strong>{report.company_name}</strong>
                    <p>{report.asset_name || report.program_target || "Unnamed program"}</p>
                    <div className="report-meta">
                      <span>{report.status}</span>
                      <span>{report.radar_score?.toFixed?.(1) ?? report.radar_score}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </DetailBlock>

          <DetailBlock title="Radar Report Detail" hint={selectedRadarReport?.opportunity_id || "select a dossier"}>
            {!selectedRadarReport ? (
              <EmptyState title="No dossier selected" body="Choose a radar report to inspect scoring and dossier markdown." />
            ) : (
              <>
                <div className="detail-actions">
                  {selectedRadarReport.report?.dossier_path ? (
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() =>
                        void downloadProtected(
                          `${MONITOR_BASE}/agent/reports/radar/opportunities/${selectedRadarReport.opportunity_id}/download`,
                          `${selectedRadarReport.opportunity_id}.md`,
                        )
                      }
                    >
                      Download Dossier
                    </button>
                  ) : null}
                </div>
                <pre>{JSON.stringify(selectedRadarReport.report || {}, null, 2)}</pre>
              </>
            )}
          </DetailBlock>
        </div>
      </section>
    </main>
  );
}
