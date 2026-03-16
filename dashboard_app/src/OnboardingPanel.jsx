import { useEffect, useMemo, useState } from "react";

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

function csvToList(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToCsv(value) {
  return (value || []).join(", ");
}

function CandidateCard({ candidate, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`candidate-card${selected ? " selected" : ""}`}
      onClick={onSelect}
    >
      <div className="candidate-card-head">
        <strong>{candidate.display_name}</strong>
        <span>{Math.round(candidate.confidence_score * 100)}%</span>
      </div>
      <p>{candidate.summary || "No public summary captured yet."}</p>
      <div className="candidate-card-meta">
        <span>{candidate.website || "no website"}</span>
        <span>{candidate.linkedin_url ? "LinkedIn found" : "LinkedIn missing"}</span>
      </div>
    </button>
  );
}

function CategoryEditor({ category, onChange, onRemove }) {
  return (
    <div className={`onboarding-card category-editor ${category.status === "removed" ? "muted" : ""}`}>
      <div className="category-editor-head">
        <strong>{category.title || "New Category"}</strong>
        <button type="button" className="btn-outline compact" onClick={onRemove}>
          Remove
        </button>
      </div>

      <div className="form-grid two-up">
        <label className="field">
          <span>Title</span>
          <input
            value={category.title}
            onChange={(event) => onChange({ ...category, title: event.target.value })}
          />
        </label>
        <label className="field">
          <span>Priority</span>
          <select
            value={category.priority}
            onChange={(event) => onChange({ ...category, priority: event.target.value })}
          >
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
        </label>
      </div>

      <div className="form-grid two-up">
        <label className="field">
          <span>Sensitivity</span>
          <select
            value={category.sensitivity}
            onChange={(event) =>
              onChange({ ...category, sensitivity: event.target.value })
            }
          >
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
            <option value="digest_only">digest_only</option>
          </select>
        </label>
        <label className="field">
          <span>Status</span>
          <select
            value={category.status}
            onChange={(event) => onChange({ ...category, status: event.target.value })}
          >
            <option value="approved">approved</option>
            <option value="proposed">proposed</option>
            <option value="removed">removed</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
      </div>

      <label className="field">
        <span>Description</span>
        <textarea
          rows={3}
          value={category.description}
          onChange={(event) =>
            onChange({ ...category, description: event.target.value })
          }
        />
      </label>

      <label className="field">
        <span>Rationale</span>
        <textarea
          rows={3}
          value={category.rationale}
          onChange={(event) =>
            onChange({ ...category, rationale: event.target.value })
          }
        />
      </label>

      <div className="form-grid two-up">
        <label className="field">
          <span>Recommended Sources</span>
          <input
            value={listToCsv(category.recommended_sources_json)}
            onChange={(event) =>
              onChange({
                ...category,
                recommended_sources_json: csvToList(event.target.value),
              })
            }
          />
        </label>
        <label className="field">
          <span>Entities</span>
          <input
            value={listToCsv(category.entities_json)}
            onChange={(event) =>
              onChange({
                ...category,
                entities_json: csvToList(event.target.value),
              })
            }
          />
        </label>
      </div>

      <div className="form-grid two-up">
        <label className="field">
          <span>Keywords</span>
          <textarea
            rows={2}
            value={listToCsv(category.keywords_json)}
            onChange={(event) =>
              onChange({
                ...category,
                keywords_json: csvToList(event.target.value),
              })
            }
          />
        </label>
        <label className="field">
          <span>Negative Keywords</span>
          <textarea
            rows={2}
            value={listToCsv(category.negative_keywords_json)}
            onChange={(event) =>
              onChange({
                ...category,
                negative_keywords_json: csvToList(event.target.value),
              })
            }
          />
        </label>
      </div>

      <label className="field">
        <span>Sample Queries</span>
        <textarea
          rows={2}
          value={listToCsv(category.sample_queries_json)}
          onChange={(event) =>
            onChange({
              ...category,
              sample_queries_json: csvToList(event.target.value),
            })
          }
        />
      </label>
    </div>
  );
}

const EMPTY_CATEGORY = {
  title: "",
  description: "",
  priority: "medium",
  rationale: "",
  sensitivity: "medium",
  recommended_sources_json: [],
  entities_json: [],
  keywords_json: [],
  negative_keywords_json: [],
  sample_queries_json: [],
  status: "approved",
};

export default function OnboardingPanel({ baseUrl, onStatus }) {
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [sessionDetail, setSessionDetail] = useState(null);
  const [busyAction, setBusyAction] = useState("");
  const [materializationResult, setMaterializationResult] = useState(null);
  const [intakeForm, setIntakeForm] = useState({
    company_name: "",
    website: "",
    linkedin_url: "",
    short_description: "",
    notes: "",
    competitors: "",
    executives: "",
    products: "",
    industry: "",
    geographies: "",
    monitoring_goals: "brand visibility, competitive monitoring, thought leadership",
  });
  const [profileDraft, setProfileDraft] = useState(null);
  const [blueprintDraft, setBlueprintDraft] = useState(null);
  const [categoriesDraft, setCategoriesDraft] = useState([]);
  const [revisionNotes, setRevisionNotes] = useState("");

  async function loadSessions(preferredId = null) {
    const rows = await fetchJson(`${baseUrl}/onboarding/sessions?limit=20`);
    setSessions(rows);
    const nextId = preferredId || selectedSessionId || rows[0]?.id || "";
    if (nextId) {
      setSelectedSessionId(nextId);
      return nextId;
    }
    return "";
  }

  async function loadSession(sessionId) {
    if (!sessionId) {
      setSessionDetail(null);
      return;
    }
    const detail = await fetchJson(`${baseUrl}/onboarding/sessions/${sessionId}`);
    setSessionDetail(detail);
    setMaterializationResult(null);
  }

  async function refresh(preferredId = null) {
    const nextId = await loadSessions(preferredId);
    if (nextId) {
      await loadSession(nextId);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (!selectedSessionId) {
      return;
    }
    void loadSession(selectedSessionId);
  }, [selectedSessionId]);

  useEffect(() => {
    if (!sessionDetail) {
      setProfileDraft(null);
      setBlueprintDraft(null);
      setCategoriesDraft([]);
      setRevisionNotes("");
      return;
    }
    setProfileDraft(
      sessionDetail.company_profile
        ? {
            summary: sessionDetail.company_profile.summary || "",
            industry: sessionDetail.company_profile.industry || "",
            subindustry: sessionDetail.company_profile.subindustry || "",
            products_json: listToCsv(sessionDetail.company_profile.products_json),
            executives_json: listToCsv(sessionDetail.company_profile.executives_json),
            competitors_json: listToCsv(sessionDetail.company_profile.competitors_json),
            themes_json: listToCsv(sessionDetail.company_profile.themes_json),
            risk_themes_json: listToCsv(sessionDetail.company_profile.risk_themes_json),
            opportunity_themes_json: listToCsv(
              sessionDetail.company_profile.opportunity_themes_json,
            ),
          }
        : null,
    );
    setBlueprintDraft(
      sessionDetail.blueprint
        ? {
            summary: sessionDetail.blueprint.summary || "",
            rationale: sessionDetail.blueprint.rationale || "",
          }
        : null,
    );
    setCategoriesDraft(sessionDetail.blueprint?.categories || []);
    setRevisionNotes("");
  }, [sessionDetail]);

  const currentStep = useMemo(() => {
    if (!sessionDetail) {
      return "Create a session";
    }
    return sessionDetail.session.status;
  }, [sessionDetail]);

  function intakePayload() {
    return {
      company_name: intakeForm.company_name,
      website: intakeForm.website || null,
      linkedin_url: intakeForm.linkedin_url || null,
      short_description: intakeForm.short_description || null,
      notes: intakeForm.notes || null,
      competitors: csvToList(intakeForm.competitors),
      executives: csvToList(intakeForm.executives),
      products: csvToList(intakeForm.products),
      industry: intakeForm.industry || null,
      geographies: csvToList(intakeForm.geographies),
      monitoring_goals: csvToList(intakeForm.monitoring_goals),
      created_by: "dashboard",
    };
  }

  async function performAction(label, fn) {
    setBusyAction(label);
    try {
      await fn();
    } catch (error) {
      onStatus(error.message || `${label} failed.`);
    } finally {
      setBusyAction("");
    }
  }

  async function createSession(resolveMode) {
    await performAction(resolveMode ? "resolve-intake" : "create", async () => {
      const endpoint = resolveMode
        ? `${baseUrl}/onboarding/auto`
        : `${baseUrl}/onboarding/sessions`;
      const response = await fetchJson(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(intakePayload()),
      });
      const detail = resolveMode ? response.session : response;
      setSessionDetail(detail);
      setSelectedSessionId(detail.session.id);
      await refresh(detail.session.id);
      onStatus(
        resolveMode
          ? `Company resolution complete. Waiting for company confirmation.`
          : "Onboarding session created.",
      );
    });
  }

  async function postSessionAction(path, label, body = null) {
    if (!selectedSessionId) {
      return;
    }
    await performAction(label, async () => {
      const detail = await fetchJson(
        `${baseUrl}/onboarding/sessions/${selectedSessionId}${path}`,
        {
          method: "POST",
          headers: body ? { "Content-Type": "application/json" } : {},
          body: body ? JSON.stringify(body) : undefined,
        },
      );
      setSessionDetail(detail);
      await refresh(selectedSessionId);
      onStatus(`${label} completed.`);
    });
  }

  async function approveBlueprint() {
    await postSessionAction("/review", "Approve blueprint", {
      action_type: "approve_final",
      target_type: "blueprint",
      created_by: "dashboard",
    });
  }

  async function requestRevision() {
    if (!profileDraft || !blueprintDraft) {
      return;
    }
    await postSessionAction("/review", "Request revision", {
      action_type: "request_revision",
      target_type: "blueprint",
      created_by: "dashboard",
      notes: revisionNotes || null,
      diff_json: {
        summary: blueprintDraft.summary,
        rationale: blueprintDraft.rationale,
        company_profile: {
          summary: profileDraft.summary,
          industry: profileDraft.industry,
          subindustry: profileDraft.subindustry,
          products_json: csvToList(profileDraft.products_json),
          executives_json: csvToList(profileDraft.executives_json),
          competitors_json: csvToList(profileDraft.competitors_json),
          themes_json: csvToList(profileDraft.themes_json),
          risk_themes_json: csvToList(profileDraft.risk_themes_json),
          opportunity_themes_json: csvToList(
            profileDraft.opportunity_themes_json,
          ),
        },
        categories: categoriesDraft,
      },
    });
  }

  async function rejectBlueprint() {
    await postSessionAction("/review", "Reject blueprint", {
      action_type: "reject_blueprint",
      target_type: "blueprint",
      created_by: "dashboard",
      notes: revisionNotes || null,
    });
  }

  async function runResearchAndProposal() {
    if (!selectedSessionId) {
      return;
    }
    await performAction("research-plan", async () => {
      const enriched = await fetchJson(
        `${baseUrl}/onboarding/sessions/${selectedSessionId}/enrich`,
        { method: "POST" },
      );
      setSessionDetail(enriched);
      const detailed = await fetchJson(
        `${baseUrl}/onboarding/sessions/${selectedSessionId}/generate-blueprint`,
        { method: "POST" },
      );
      setSessionDetail(detailed);
      await refresh(selectedSessionId);
      onStatus("Agent research and monitoring proposal are ready for review.");
    });
  }

  async function materialize() {
    if (!selectedSessionId) {
      return;
    }
    await performAction("materialize", async () => {
      const result = await fetchJson(
        `${baseUrl}/onboarding/sessions/${selectedSessionId}/materialize`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ created_by: "dashboard", signal_routes: [] }),
        },
      );
      setMaterializationResult(result);
      await refresh(selectedSessionId);
      onStatus(`Materialized client ${result.client_name}.`);
    });
  }

  return (
    <section className="onboarding-layout">
      <div className="onboarding-column">
        <div className="onboarding-card">
          <div className="detail-head">
            <div>
              <h3>New Session</h3>
              <span>Layer 0 intake</span>
            </div>
            <span className="report-kicker">AI-Assisted Client Setup</span>
          </div>

          <div className="form-grid two-up">
            <label className="field">
              <span>Company Name</span>
              <input
                value={intakeForm.company_name}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    company_name: event.target.value,
                  }))
                }
                placeholder="Acme Bio"
              />
            </label>
            <label className="field">
              <span>Website</span>
              <input
                value={intakeForm.website}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    website: event.target.value,
                  }))
                }
                placeholder="https://example.com"
              />
            </label>
          </div>

          <div className="form-grid two-up">
            <label className="field">
              <span>LinkedIn</span>
              <input
                value={intakeForm.linkedin_url}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    linkedin_url: event.target.value,
                  }))
                }
              />
            </label>
            <label className="field">
              <span>Industry</span>
              <input
                value={intakeForm.industry}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    industry: event.target.value,
                  }))
                }
              />
            </label>
          </div>

          <label className="field">
            <span>Short Description</span>
            <textarea
              rows={2}
              value={intakeForm.short_description}
              onChange={(event) =>
                setIntakeForm((current) => ({
                  ...current,
                  short_description: event.target.value,
                }))
              }
            />
          </label>

          <label className="field">
            <span>Notes / Priorities</span>
            <textarea
              rows={3}
              value={intakeForm.notes}
              onChange={(event) =>
                setIntakeForm((current) => ({
                  ...current,
                  notes: event.target.value,
                }))
              }
            />
          </label>

          <div className="form-grid two-up">
            <label className="field">
              <span>Competitors</span>
              <input
                value={intakeForm.competitors}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    competitors: event.target.value,
                  }))
                }
                placeholder="Competitor A, Competitor B"
              />
            </label>
            <label className="field">
              <span>Executives</span>
              <input
                value={intakeForm.executives}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    executives: event.target.value,
                  }))
                }
              />
            </label>
          </div>

          <div className="form-grid two-up">
            <label className="field">
              <span>Products</span>
              <input
                value={intakeForm.products}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    products: event.target.value,
                  }))
                }
              />
            </label>
            <label className="field">
              <span>Geographies</span>
              <input
                value={intakeForm.geographies}
                onChange={(event) =>
                  setIntakeForm((current) => ({
                    ...current,
                    geographies: event.target.value,
                  }))
                }
              />
            </label>
          </div>

          <label className="field">
            <span>Monitoring Goals</span>
            <input
              value={intakeForm.monitoring_goals}
              onChange={(event) =>
                setIntakeForm((current) => ({
                  ...current,
                  monitoring_goals: event.target.value,
                }))
              }
            />
          </label>

          <div className="detail-actions">
            <button
              type="button"
              className="btn-outline"
              onClick={() => void createSession(false)}
              disabled={!intakeForm.company_name || busyAction !== ""}
            >
              {busyAction === "create" ? "Creating..." : "Create Draft"}
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => void createSession(true)}
              disabled={!intakeForm.company_name || busyAction !== ""}
            >
              {busyAction === "resolve-intake" ? "Resolving..." : "Create + Resolve Company"}
            </button>
          </div>
        </div>

        <div className="onboarding-card">
          <div className="detail-head">
            <div>
              <h3>Sessions</h3>
              <span>Recent onboarding attempts</span>
            </div>
            <span>{sessions.length}</span>
          </div>

          <div className="session-list">
            {sessions.length === 0 ? (
              <div className="empty-state compact">
                <strong>No sessions yet</strong>
                <p>Create a new onboarding request to start Layer 0.</p>
              </div>
            ) : (
              sessions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`session-pill${selectedSessionId === item.id ? " active" : ""}`}
                  onClick={() => setSelectedSessionId(item.id)}
                >
                  <strong>{item.company_name_input}</strong>
                  <span>{item.status}</span>
                  <small>{formatTimestamp(item.updated_at)}</small>
                </button>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="onboarding-column wide">
        <div className="onboarding-card">
          <div className="detail-head">
            <div>
              <h3>Workflow State</h3>
              <span>Current step: {currentStep}</span>
            </div>
            <div className="detail-actions">
              <button
                type="button"
                className="btn-outline"
                onClick={() => void postSessionAction("/resolve", "Resolve company")}
                disabled={!selectedSessionId || busyAction !== ""}
              >
                Resolve Company
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => void runResearchAndProposal()}
                disabled={!selectedSessionId || !sessionDetail?.selected_candidate || busyAction !== ""}
              >
                Research + Draft Proposal
              </button>
            </div>
          </div>

          {!sessionDetail ? (
            <div className="empty-state compact">
              <strong>No active session</strong>
              <p>Select a session to inspect the onboarding workflow.</p>
            </div>
          ) : (
            <div className="detail-stack">
              {sessionDetail.disambiguation_prompt ? (
                <div className="inline-banner">
                  <strong>Disambiguation</strong>
                  <p>{sessionDetail.disambiguation_prompt}</p>
                </div>
              ) : null}

              <div className="identity-grid">
                <div className="onboarding-card nested">
                  <div className="detail-head">
                    <div>
                      <h3>Company Identity</h3>
                      <span>Resolve and confirm the target company</span>
                    </div>
                  </div>
                  <div className="candidate-grid">
                    {sessionDetail.candidates.length === 0 ? (
                      <div className="empty-state compact">
                        <strong>No candidates</strong>
                        <p>Run company resolution to generate public matches.</p>
                      </div>
                    ) : (
                      sessionDetail.candidates.map((candidate) => (
                        <CandidateCard
                          key={candidate.id}
                          candidate={candidate}
                          selected={candidate.is_selected}
                          onSelect={() =>
                            void postSessionAction("/confirm-candidate", "Confirm candidate", {
                              candidate_id: candidate.id,
                            })
                          }
                        />
                      ))
                    )}
                  </div>
                </div>

                <div className="onboarding-card nested">
                  <div className="detail-head">
                    <div>
                      <h3>Resolved Profile</h3>
                      <span>Editable before blueprint approval</span>
                    </div>
                  </div>
                  {!profileDraft ? (
                    <div className="empty-state compact">
                      <strong>No profile yet</strong>
                      <p>Confirm a company and run enrichment.</p>
                    </div>
                  ) : (
                    <div className="form-stack">
                      <label className="field">
                        <span>Summary</span>
                        <textarea
                          rows={4}
                          value={profileDraft.summary}
                          onChange={(event) =>
                            setProfileDraft((current) => ({
                              ...current,
                              summary: event.target.value,
                            }))
                          }
                        />
                      </label>

                      <div className="form-grid two-up">
                        <label className="field">
                          <span>Industry</span>
                          <input
                            value={profileDraft.industry}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                industry: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <label className="field">
                          <span>Subindustry</span>
                          <input
                            value={profileDraft.subindustry}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                subindustry: event.target.value,
                              }))
                            }
                          />
                        </label>
                      </div>

                      <div className="form-grid two-up">
                        <label className="field">
                          <span>Products</span>
                          <textarea
                            rows={2}
                            value={profileDraft.products_json}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                products_json: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <label className="field">
                          <span>Executives</span>
                          <textarea
                            rows={2}
                            value={profileDraft.executives_json}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                executives_json: event.target.value,
                              }))
                            }
                          />
                        </label>
                      </div>

                      <div className="form-grid two-up">
                        <label className="field">
                          <span>Competitors</span>
                          <textarea
                            rows={2}
                            value={profileDraft.competitors_json}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                competitors_json: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <label className="field">
                          <span>Themes</span>
                          <textarea
                            rows={2}
                            value={profileDraft.themes_json}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                themes_json: event.target.value,
                              }))
                            }
                          />
                        </label>
                      </div>

                      <div className="form-grid two-up">
                        <label className="field">
                          <span>Risk Themes</span>
                          <textarea
                            rows={2}
                            value={profileDraft.risk_themes_json}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                risk_themes_json: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <label className="field">
                          <span>Opportunity Themes</span>
                          <textarea
                            rows={2}
                            value={profileDraft.opportunity_themes_json}
                            onChange={(event) =>
                              setProfileDraft((current) => ({
                                ...current,
                                opportunity_themes_json: event.target.value,
                              }))
                            }
                          />
                        </label>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="onboarding-card nested">
                <div className="detail-head">
                  <div>
                    <h3>Monitoring Blueprint</h3>
                    <span>Review the proposal, request revisions, then approve activation</span>
                  </div>
                  <div className="detail-actions">
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() =>
                        setCategoriesDraft((current) => [
                          ...current,
                          { ...EMPTY_CATEGORY, id: undefined },
                        ])
                      }
                      disabled={!sessionDetail.blueprint}
                    >
                      Add Category
                    </button>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() => void requestRevision()}
                      disabled={!sessionDetail.blueprint || busyAction !== ""}
                    >
                      Request Revision
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => void approveBlueprint()}
                      disabled={!sessionDetail.blueprint || busyAction !== ""}
                    >
                      Final Approve
                    </button>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() => void rejectBlueprint()}
                      disabled={!sessionDetail.blueprint || busyAction !== ""}
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => void materialize()}
                      disabled={
                        !sessionDetail.blueprint ||
                        sessionDetail.session.status !== "approved" ||
                        busyAction !== ""
                      }
                    >
                      Activate Monitoring
                    </button>
                  </div>
                </div>

                {!sessionDetail.blueprint || !blueprintDraft ? (
                  <div className="empty-state compact">
                    <strong>No blueprint yet</strong>
                    <p>Generate a blueprint after enrichment.</p>
                  </div>
                ) : (
                  <div className="detail-stack">
                    <div className="form-grid two-up">
                      <label className="field">
                        <span>Summary</span>
                        <textarea
                          rows={3}
                          value={blueprintDraft.summary}
                          onChange={(event) =>
                            setBlueprintDraft((current) => ({
                              ...current,
                              summary: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Rationale</span>
                        <textarea
                          rows={3}
                          value={blueprintDraft.rationale}
                          onChange={(event) =>
                            setBlueprintDraft((current) => ({
                              ...current,
                              rationale: event.target.value,
                            }))
                          }
                        />
                      </label>
                    </div>

                    <label className="field">
                      <span>Revision Notes For Agent</span>
                      <textarea
                        rows={3}
                        value={revisionNotes}
                        onChange={(event) => setRevisionNotes(event.target.value)}
                        placeholder="Tell the agent what to change, what is wrong, what to emphasize, or what to remove."
                      />
                    </label>

                    <div className="category-stack">
                      {categoriesDraft.map((category, index) => (
                        <CategoryEditor
                          key={category.id || `new-${index}`}
                          category={category}
                          onChange={(next) =>
                            setCategoriesDraft((current) =>
                              current.map((item, itemIndex) =>
                                itemIndex === index ? next : item,
                              ),
                            )
                          }
                          onRemove={() =>
                            setCategoriesDraft((current) =>
                              current.map((item, itemIndex) =>
                                itemIndex === index
                                  ? { ...item, status: "removed" }
                                  : item,
                              ),
                            )
                          }
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {materializationResult ? (
                <div className="inline-banner success">
                  <strong>Materialized</strong>
                  <p>
                    {materializationResult.client_name} is now live with{" "}
                    {materializationResult.topic_ids.length} topics and{" "}
                    {materializationResult.subscription_ids.length} subscriptions.
                  </p>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
