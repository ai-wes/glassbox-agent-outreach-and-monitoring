from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from pr_monitor_app.api_schemas import (
    OpenClawAnalysisContext,
    OpenClawBrandCatalogItem,
    OpenClawBrandConfig,
    OpenClawBrandResolution,
    OpenClawClientContext,
    OpenClawDailyPodcastReport,
    OpenClawEventContext,
    OpenClawInstructions,
    OpenClawJobContext,
    OpenClawJobRef,
    OpenClawRiskContext,
    OpenClawTopTopic,
)
from pr_monitor_app.db_sync import sync_db_session
from pr_monitor_app.models import BrandConfigDB, Client, DailyPodcastReport, IngestionEvent, TopicLens
from pr_monitor_app.models_analytics import EventAnalysis, EventTopicScore
from pr_monitor_app.models_agent import AgentJob, AgentJobStatus, AgentOutput, ClientProfile


def utcnow() -> datetime:
    return datetime.utcnow()


class AgentProcessor:
    def claim_next_for_openclaw(
        self,
        *,
        batch_size: int,
        brand_name: str | None = None,
        brand_config_id: uuid.UUID | None = None,
    ) -> list[OpenClawJobContext]:
        with sync_db_session() as session:
            jobs = (
                session.execute(
                    select(AgentJob)
                    .where(AgentJob.status == AgentJobStatus.pending)
                    .order_by(AgentJob.priority.asc(), AgentJob.created_at.asc())
                    .limit(int(batch_size))
                )
                .scalars()
                .all()
            )

            claimed: list[OpenClawJobContext] = []
            for job in jobs:
                context = self._build_job_context(
                    session,
                    job,
                    brand_name=brand_name,
                    brand_config_id=brand_config_id,
                )
                job.status = AgentJobStatus.processing
                job.started_at = job.started_at or utcnow()
                job.updated_at = utcnow()
                job.error_message = None
                claimed.append(context)

            session.flush()
            return claimed

    def complete_job_from_openclaw(
        self,
        *,
        job_id: uuid.UUID,
        output_json: dict[str, Any],
        model: str,
        summary_text: str | None,
        meta_json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with sync_db_session() as session:
            job = session.get(AgentJob, job_id)
            if job is None:
                raise ValueError("job not found")

            output = (
                session.execute(
                    select(AgentOutput).where(
                        AgentOutput.event_id == job.event_id,
                        AgentOutput.client_id == job.client_id,
                        AgentOutput.agent_version == job.agent_version,
                    )
                )
                .scalars()
                .first()
            )
            if output is None:
                output = AgentOutput(
                    event_id=job.event_id,
                    client_id=job.client_id,
                    agent_version=job.agent_version,
                    model=model,
                    output_json=dict(output_json or {}),
                    summary_text=summary_text,
                    meta_json=dict(meta_json or {}),
                )
                session.add(output)
                session.flush()
            else:
                output.model = model
                output.output_json = dict(output_json or {})
                output.summary_text = summary_text
                output.meta_json = dict(meta_json or {})
                output.generated_at = utcnow()

            job.status = AgentJobStatus.completed
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            job.output_id = output.id
            job.error_message = None
            session.flush()

            return {
                "job_id": str(job.id),
                "output_id": str(output.id),
                "status": job.status.value,
            }

    def fail_job_from_openclaw(self, *, job_id: uuid.UUID, error_message: str) -> dict[str, Any]:
        with sync_db_session() as session:
            job = session.get(AgentJob, job_id)
            if job is None:
                raise ValueError("job not found")

            job.status = AgentJobStatus.error
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            job.error_message = error_message.strip()[:4000]
            session.flush()

            return {"job_id": str(job.id), "status": job.status.value}

    def _build_job_context(
        self,
        session,
        job: AgentJob,
        *,
        brand_name: str | None,
        brand_config_id: uuid.UUID | None,
    ) -> OpenClawJobContext:
        client = session.get(Client, job.client_id)
        event = session.get(IngestionEvent, job.event_id)
        if client is None or event is None:
            raise ValueError(f"job {job.id} references missing client or event")

        profile = session.get(ClientProfile, job.client_id)
        analysis = (
            session.execute(select(EventAnalysis).where(EventAnalysis.event_id == job.event_id))
            .scalars()
            .first()
        )
        top_topics = self._load_top_topics(session, job.event_id)
        selected_brand_config, resolution, catalog = self._resolve_brand_config(
            session,
            client=client,
            brand_name=brand_name,
            brand_config_id=brand_config_id,
        )
        daily_report = self._latest_daily_report(session)

        frames = []
        if analysis is not None:
            frames = list(analysis.frames_json or [])

        return OpenClawJobContext(
            job=OpenClawJobRef(
                id=job.id,
                event_id=job.event_id,
                client_id=job.client_id,
                priority=job.priority,
                top_relevance_score=float(job.top_relevance_score or 0.0),
                agent_version=job.agent_version,
            ),
            client=OpenClawClientContext(
                id=client.id,
                name=client.name,
                voice_instructions=profile.voice_instructions if profile else None,
                do_not_say=list(profile.do_not_say_json or []) if profile else [],
                default_hashtags=list(profile.default_hashtags_json or []) if profile else [],
                compliance_notes=profile.compliance_notes if profile else None,
            ),
            event=OpenClawEventContext(
                id=event.id,
                title=event.title,
                url=event.canonical_url,
                summary=event.summary,
                fetched_at=event.fetched_at.isoformat() if event.fetched_at else None,
                excerpt=(event.content_text or event.summary or event.title or "")[:4000],
            ),
            analysis=OpenClawAnalysisContext(
                sentiment_label=analysis.sentiment_label if analysis else None,
                sentiment_score=analysis.sentiment_score if analysis else None,
                frames=frames,
                top_topics=top_topics,
                risk=OpenClawRiskContext(
                    level=self._risk_level(job.priority),
                    notes=self._risk_notes(client=client, analysis=analysis),
                ),
            ),
            brand_config=selected_brand_config,
            brand_config_resolution=resolution,
            brand_config_catalog=catalog,
            daily_podcast_report=daily_report,
            instructions=OpenClawInstructions(
                output_contract="Return a structured JSON result plus a concise summary_text.",
                brand_config_usage="If a brand config is present, treat it as the source of truth for brand facts and claims.",
            ),
        )

    def _load_top_topics(self, session, event_id: uuid.UUID) -> list[OpenClawTopTopic]:
        rows = session.execute(
            select(EventTopicScore, TopicLens)
            .join(TopicLens, TopicLens.id == EventTopicScore.topic_id)
            .where(EventTopicScore.event_id == event_id)
            .order_by(EventTopicScore.relevance_score.desc())
            .limit(5)
        ).all()
        return [
            OpenClawTopTopic(
                id=topic.id,
                name=topic.name,
                relevance_score=float(score.relevance_score),
                keywords=list(topic.keywords or []),
            )
            for score, topic in rows
        ]

    def _resolve_brand_config(
        self,
        session,
        *,
        client: Client,
        brand_name: str | None,
        brand_config_id: uuid.UUID | None,
    ) -> tuple[OpenClawBrandConfig | None, OpenClawBrandResolution, list[OpenClawBrandCatalogItem]]:
        total = session.execute(select(func.count()).select_from(BrandConfigDB)).scalar_one()
        catalog_rows = (
            session.execute(
                select(BrandConfigDB).order_by(BrandConfigDB.updated_at.desc()).limit(20)
            )
            .scalars()
            .all()
        )
        catalog = [
            OpenClawBrandCatalogItem(
                id=row.id,
                brand_name=row.brand_name,
                official_website=row.official_website,
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            )
            for row in catalog_rows
        ]

        source = "none"
        row = None
        if brand_config_id is not None:
            row = session.get(BrandConfigDB, brand_config_id)
            source = "brand_config_id"
        elif brand_name:
            row = (
                session.execute(
                    select(BrandConfigDB).where(BrandConfigDB.brand_name == brand_name.strip())
                )
                .scalars()
                .first()
            )
            source = "brand_name"
        else:
            row = (
                session.execute(
                    select(BrandConfigDB).where(BrandConfigDB.brand_name == client.name)
                )
                .scalars()
                .first()
            )
            source = "client_name"

        brand_config = None
        if row is not None:
            brand_config = OpenClawBrandConfig(
                id=row.id,
                brand_name=row.brand_name,
                brand_domains=list(row.brand_domains or []),
                brand_aliases=list(row.brand_aliases or []),
                key_claims=dict(row.key_claims or {}),
                competitors=list(row.competitors or []),
                executive_names=list(row.executive_names or []),
                official_website=row.official_website,
                social_profiles=list(row.social_profiles or []),
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            )

        return (
            brand_config,
            OpenClawBrandResolution(source=source, available_count=int(total or 0)),
            catalog,
        )

    def _latest_daily_report(self, session) -> OpenClawDailyPodcastReport | None:
        row = (
            session.execute(
                select(DailyPodcastReport).order_by(DailyPodcastReport.created_at.desc()).limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            return None

        return OpenClawDailyPodcastReport(
            id=row.id,
            report_date=row.report_date.isoformat() if row.report_date else None,
            title=row.title,
            created_at=row.created_at.isoformat() if row.created_at else None,
            summary_excerpt=(row.report_md or "")[:280].strip(),
            report_md=row.report_md,
            source_path=row.source_path,
            status=row.status,
        )

    def _risk_level(self, priority: str) -> str:
        if priority == "P0":
            return "high"
        if priority == "P1":
            return "medium"
        return "normal"

    def _risk_notes(self, *, client: Client, analysis: EventAnalysis | None) -> list[str]:
        notes: list[str] = []
        if client.risk_keywords:
            notes.append(f"Configured risk keywords: {', '.join(client.risk_keywords[:10])}")
        if analysis and analysis.sentiment_label:
            notes.append(f"Detected sentiment: {analysis.sentiment_label}")
        return notes
