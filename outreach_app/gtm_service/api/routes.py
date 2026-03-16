from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from outreach_app.gtm_service.db.models import (
    Company,
    ConversionEvent,
    ConversionEventType,
    DeliveryEvent,
    DeliveryEventType,
    Lead,
    LeadScore,
    LeadStatus,
    MessageStatus,
    OutreachMessage,
    OutreachSequence,
    ReplyEvent,
    ReplyType,
)
from outreach_app.gtm_service.db.session import get_db_session
from outreach_app.gtm_service.schemas.common import HealthResponse
from outreach_app.gtm_service.schemas.lead import (
    CSVImportResponse,
    CandidateIngestRequest,
    LeadRead,
    PipelineResult,
    ReplyEventCreate,
    ReplyEventRead,
    SignalRead,
)
from outreach_app.gtm_service.schemas.outreach import (
    MessageApprovalRequest,
    OutreachMessageRead,
    SequencePreview,
    SequenceQueueRequest,
)
from outreach_app.gtm_service.schemas.prospecting import (
    DomainDiscoveryRequest,
    LimitedRunRequest,
    ProspectingRunRead,
)
from outreach_app.gtm_service.schemas.telemetry import (
    AttributionPerformanceRead,
    ConversionEventCreate,
    ConversionEventRead,
    DeliveryEventCreate,
    DeliveryEventRead,
    FunnelMetricsRead,
    LeadTelemetryRead,
    MetricsDashboardRead,
    SequencePerformanceRead,
    StepPerformanceRead,
)
from outreach_app.gtm_service.services.container import ServiceContainer
from outreach_app.gtm_service.services.orchestrator import PipelineOrchestrator
from outreach_app.gtm_service.services.research import ResearchOutput

router = APIRouter()


class RSSImportRequest(BaseModel):
    feed_url: str
    auto_queue: bool = False


class CSVImportRequest(BaseModel):
    csv_text: str


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.gtm_container


def build_orchestrator(container: ServiceContainer, session: AsyncSession) -> PipelineOrchestrator:
    return PipelineOrchestrator(
        settings=container.settings,
        session=session,
        source_service=container.source_service,
        research_agent=container.research_agent,
        scoring_service=container.scoring_service,
        router=container.router,
        sequence_service=container.sequence_service,
        crm_sync_service=container.crm_sync_service,
    )


@router.get('/health', response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.gtm_settings
    return HealthResponse(status='ok', app=settings.app_name, environment=settings.app_env, timestamp=datetime.now(timezone.utc))


@router.post('/pipeline/ingest', response_model=PipelineResult)
async def ingest_pipeline(payload: CandidateIngestRequest, session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)) -> PipelineResult:
    orchestrator = build_orchestrator(container, session)
    return await orchestrator.ingest_candidate(payload)


@router.post('/pipeline/import-csv', response_model=CSVImportResponse)
async def import_csv(payload: CSVImportRequest, session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)) -> CSVImportResponse:
    candidates = container.source_service.import_csv(payload.csv_text.encode("utf-8"))
    orchestrator = build_orchestrator(container, session)
    lead_ids: list[str] = []
    for candidate in candidates:
        result = await orchestrator.ingest_candidate(candidate)
        lead_ids.append(result.lead_id)
    return CSVImportResponse(imported=len(lead_ids), lead_ids=lead_ids)


@router.post('/pipeline/import-rss', response_model=CSVImportResponse)
async def import_rss(payload: RSSImportRequest, session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)) -> CSVImportResponse:
    rss_result = await container.source_service.import_rss(payload.feed_url)
    orchestrator = build_orchestrator(container, session)
    lead_ids: list[str] = []
    for candidate in rss_result.items:
        candidate.auto_queue = payload.auto_queue
        result = await orchestrator.ingest_candidate(candidate)
        lead_ids.append(result.lead_id)
    return CSVImportResponse(imported=len(lead_ids), lead_ids=lead_ids)


@router.get('/leads', response_model=list[LeadRead])
@router.get('/api/leads', response_model=list[LeadRead], include_in_schema=False)
async def list_leads(
    status: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[LeadRead]:
    stmt = select(Lead)
    if status:
        stmt = stmt.where(Lead.status == _coerce_lead_status(status))
    stmt = (
        stmt
        .order_by(Lead.updated_at.desc())
        .limit(min(max(limit, 1), 500))
        .options(
            selectinload(Lead.company).selectinload(Company.signals),
            selectinload(Lead.contact),
            selectinload(Lead.scores),
        )
    )
    leads = list((await session.execute(stmt)).scalars().unique().all())
    return [_lead_read(lead) for lead in leads]


@router.post("/discovery", response_model=ProspectingRunRead)
@router.post("/api/discovery", response_model=ProspectingRunRead, include_in_schema=False)
async def trigger_discovery(
    payload: DomainDiscoveryRequest,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> ProspectingRunRead:
    if not payload.domains:
        raise HTTPException(status_code=400, detail="domains list cannot be empty")
    result = await container.prospecting_service.discover_from_domains(session, payload.domains)
    return ProspectingRunRead.model_validate(result)


@router.post("/enrich", response_model=ProspectingRunRead)
@router.post("/api/enrich", response_model=ProspectingRunRead, include_in_schema=False)
async def trigger_enrichment(
    payload: LimitedRunRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> ProspectingRunRead:
    result = await container.prospecting_service.enrich_leads(session, limit=(payload.limit if payload else 100))
    return ProspectingRunRead.model_validate(result)


@router.post("/verify", response_model=ProspectingRunRead)
@router.post("/api/verify", response_model=ProspectingRunRead, include_in_schema=False)
async def trigger_verification(
    payload: LimitedRunRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> ProspectingRunRead:
    result = await container.prospecting_service.verify_leads(session, limit=(payload.limit if payload else 100))
    return ProspectingRunRead.model_validate(result)


@router.post("/score", response_model=ProspectingRunRead)
@router.post("/api/score", response_model=ProspectingRunRead, include_in_schema=False)
async def trigger_scoring(
    payload: LimitedRunRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> ProspectingRunRead:
    result = await container.prospecting_service.score_leads(session, limit=(payload.limit if payload else 100))
    return ProspectingRunRead.model_validate(result)


@router.post("/sync", response_model=ProspectingRunRead)
@router.post("/api/sync", response_model=ProspectingRunRead, include_in_schema=False)
async def trigger_sync(
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> ProspectingRunRead:
    if not container.crm_sync_service.enabled:
        raise HTTPException(status_code=503, detail="Google Sheets CRM sync is not configured")
    result = await container.prospecting_service.sync_to_crm(session)
    return ProspectingRunRead.model_validate(result)


@router.get('/leads/{lead_id}', response_model=LeadRead)
async def get_lead(lead_id: str, session: AsyncSession = Depends(get_db_session)) -> LeadRead:
    stmt = (
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.company).selectinload(Company.signals),
            selectinload(Lead.contact),
            selectinload(Lead.scores),
        )
    )
    lead = (await session.execute(stmt)).scalars().unique().one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail='Lead not found')
    return _lead_read(lead)


@router.get('/leads/{lead_id}/sequence-preview', response_model=SequencePreview)
async def sequence_preview(lead_id: str, session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)) -> SequencePreview:
    stmt = select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.company), selectinload(Lead.contact))
    lead = (await session.execute(stmt)).scalars().unique().one_or_none()
    if lead is None or lead.company is None or not lead.recommended_sequence:
        raise HTTPException(status_code=404, detail='Lead or sequence not found')
    research = ResearchOutput(
        icp_class=lead.icp_class or 'ai_bio_startup',
        persona_class=lead.persona_class or 'founder',
        why_now=lead.why_now or [],
        pain_hypotheses=[],
        offer_recommendation=lead.recommended_offer or 'Standard run',
        sequence_recommendation=lead.recommended_sequence,
        proof_angle='',
        trigger_line=(lead.why_now[0] if lead.why_now else f'{lead.company.name} is active'),
        trigger_short=(lead.why_now[0] if lead.why_now else f'{lead.company.name} is active'),
        partner_intro='A partner thought this might be relevant.',
        extracted_signals=[],
        confidence=lead.confidence,
    )
    return container.outreach_generator.preview_sequence(sequence_key=lead.recommended_sequence, company_name=lead.company.name, contact_first_name=lead.contact.first_name if lead.contact else None, research=research)


@router.post('/leads/{lead_id}/queue')
async def queue_lead(lead_id: str, payload: SequenceQueueRequest, session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)) -> dict[str, str]:
    try:
        sequence = await container.sequence_service.queue_lead(session, lead_id=lead_id, force=payload.force, start_immediately=payload.start_immediately)
        return {'sequence_id': sequence.id, 'status': sequence.status.value}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/sequences/run-due')
async def run_due(session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)):
    return await container.sequence_service.run_due_messages(session)


@router.get("/messages/pending-approval", response_model=list[OutreachMessageRead])
async def list_pending_message_approvals(
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[OutreachMessageRead]:
    stmt = (
        select(OutreachMessage)
        .where(OutreachMessage.status == MessageStatus.AWAITING_MANUAL)
        .order_by(OutreachMessage.scheduled_for.asc(), OutreachMessage.created_at.asc())
        .limit(min(max(limit, 1), 500))
    )
    messages = list((await session.execute(stmt)).scalars().all())
    return [OutreachMessageRead.model_validate(message) for message in messages]


@router.post("/messages/{message_id}/approve", response_model=OutreachMessageRead)
async def approve_message(
    message_id: str,
    payload: MessageApprovalRequest,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> OutreachMessageRead:
    try:
        message = await container.sequence_service.approve_message(
            session,
            message_id=message_id,
            approved_by=payload.approved_by,
            notes=payload.notes,
            send_immediately=payload.send_immediately,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OutreachMessageRead.model_validate(message)


@router.post("/messages/{message_id}/reject", response_model=OutreachMessageRead)
async def reject_message(
    message_id: str,
    payload: MessageApprovalRequest,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> OutreachMessageRead:
    try:
        message = await container.sequence_service.reject_message(
            session,
            message_id=message_id,
            rejected_by=payload.approved_by,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OutreachMessageRead.model_validate(message)


@router.post('/replies')
async def record_reply(payload: ReplyEventCreate, session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)) -> dict[str, str]:
    lead = (
        await session.execute(
            select(Lead)
            .where(Lead.id == payload.lead_id)
            .options(selectinload(Lead.company), selectinload(Lead.contact))
        )
    ).scalars().one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail='Lead not found')
    try:
        reply_type = ReplyType(payload.reply_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Invalid reply_type') from exc
    metadata_json = dict(payload.metadata_json or {})
    if payload.intent_label:
        metadata_json["intent_label"] = payload.intent_label
    message = None
    if payload.outreach_message_id:
        message = (
            await session.execute(
                select(OutreachMessage)
                .where(OutreachMessage.id == payload.outreach_message_id)
                .options(selectinload(OutreachMessage.sequence))
            )
        ).scalars().one_or_none()
    event = ReplyEvent(
        lead_id=payload.lead_id,
        outreach_message_id=payload.outreach_message_id,
        raw_text=payload.raw_text,
        reply_type=reply_type,
        sentiment=payload.sentiment,
        metadata_json=metadata_json,
    )
    session.add(event)
    if reply_type == ReplyType.POSITIVE:
        lead.status = LeadStatus.RESPONDED_POSITIVE
    elif reply_type in {ReplyType.NEGATIVE, ReplyType.WRONG_PERSON, ReplyType.NOT_NOW}:
        lead.status = LeadStatus.RESPONDED_NEGATIVE
    await session.commit()
    await container.sequence_service.stop_active_sequences_for_lead(session, payload.lead_id)
    if container.crm_sync_service.enabled:
        container.crm_sync_service.sync_reply_record(
            reply=event,
            lead=lead,
            message=message,
            company=lead.company,
            contact=lead.contact,
        )
        await container.crm_sync_service.sync_lead_from_db(session=session, lead_id=lead.id)
    return {'status': 'recorded'}


@router.post("/messages/{message_id}/delivery-events", response_model=DeliveryEventRead)
async def record_delivery_event(
    message_id: str,
    payload: DeliveryEventCreate,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> DeliveryEventRead:
    event_type = _coerce_delivery_event_type(payload.event_type)
    message = (
        await session.execute(
            select(OutreachMessage)
            .where(OutreachMessage.id == message_id)
            .options(
                selectinload(OutreachMessage.sequence)
                .selectinload(OutreachSequence.lead)
                .selectinload(Lead.company),
                selectinload(OutreachMessage.sequence)
                .selectinload(OutreachSequence.lead)
                .selectinload(Lead.contact),
            )
        )
    ).scalars().one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    lead_id = message.sequence.lead_id if message.sequence else None
    event = DeliveryEvent(
        outreach_message_id=message.id,
        lead_id=lead_id,
        event_type=event_type.value,
        provider_event_id=payload.provider_event_id,
        reason=payload.reason,
        metadata_json=payload.metadata_json,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    if container.crm_sync_service.enabled:
        sequence = message.sequence
        lead = sequence.lead if sequence else None
        container.crm_sync_service.sync_delivery_event_record(
            event=event,
            lead=lead,
            sequence=sequence,
            message=message,
            company=lead.company if lead else None,
            contact=lead.contact if lead else None,
        )
    return DeliveryEventRead.model_validate(event)


@router.post("/leads/{lead_id}/conversion-events", response_model=ConversionEventRead)
async def record_conversion_event(
    lead_id: str,
    payload: ConversionEventCreate,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> ConversionEventRead:
    event_type = _coerce_conversion_event_type(payload.event_type)
    lead = (
        await session.execute(
            select(Lead)
            .where(Lead.id == lead_id)
            .options(
                selectinload(Lead.sequences),
                selectinload(Lead.company),
                selectinload(Lead.contact),
            )
        )
    ).scalars().one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    if payload.sequence_id is not None:
        sequence = next((sequence for sequence in lead.sequences if sequence.id == payload.sequence_id), None)
        if sequence is None:
            raise HTTPException(status_code=400, detail="sequence does not belong to lead")
    conversion = ConversionEvent(
        lead_id=lead_id,
        sequence_id=payload.sequence_id,
        reply_event_id=payload.reply_event_id,
        event_type=event_type.value,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
        value=payload.value,
        external_ref=payload.external_ref,
        metadata_json=payload.metadata_json,
    )
    session.add(conversion)
    await session.commit()
    await session.refresh(conversion)
    if container.crm_sync_service.enabled:
        company = lead.company if hasattr(lead, "company") else None
        contact = lead.contact if hasattr(lead, "contact") else None
        sequence = next((item for item in lead.sequences if item.id == conversion.sequence_id), None) if conversion.sequence_id else None
        container.crm_sync_service.sync_conversion_event_record(
            event=conversion,
            lead=lead,
            sequence=sequence,
            company=company,
            contact=contact,
        )
        await container.crm_sync_service.sync_lead_from_db(session=session, lead_id=lead.id)
    return ConversionEventRead.model_validate(conversion)


@router.post("/sheets/full-sync")
async def sheets_full_sync(
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> dict[str, Any]:
    if not container.crm_sync_service.enabled:
        raise HTTPException(status_code=503, detail="Google Sheets CRM sync is not configured")
    return await container.crm_sync_service.full_sync(session=session, metrics_service=container.metrics_service)


@router.get('/replies', response_model=list[ReplyEventRead])
async def list_replies(
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[ReplyEventRead]:
    stmt = (
        select(ReplyEvent)
        .order_by(ReplyEvent.created_at.desc())
        .limit(limit)
        .options(
            selectinload(ReplyEvent.lead).selectinload(Lead.company),
            selectinload(ReplyEvent.lead).selectinload(Lead.contact),
            selectinload(ReplyEvent.outreach_message).selectinload(OutreachMessage.sequence),
        )
    )
    replies = (await session.execute(stmt)).scalars().all()
    return [_reply_read(reply) for reply in replies]


@router.get('/metrics/summary')
async def metrics_summary(session: AsyncSession = Depends(get_db_session), container: ServiceContainer = Depends(get_container)):
    return await container.metrics_service.summary(session)


@router.get("/metrics/sequences", response_model=list[SequencePerformanceRead])
async def metrics_sequences(
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> list[SequencePerformanceRead]:
    return await container.metrics_service.sequence_performance(session, limit=limit)


@router.get("/metrics/steps", response_model=list[StepPerformanceRead])
async def metrics_steps(
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> list[StepPerformanceRead]:
    return await container.metrics_service.step_performance(session)


@router.get("/metrics/attribution", response_model=list[AttributionPerformanceRead])
async def metrics_attribution(
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> list[AttributionPerformanceRead]:
    return await container.metrics_service.attribution_breakdown(session, limit=limit)


@router.get("/metrics/funnel", response_model=FunnelMetricsRead)
async def metrics_funnel(
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> FunnelMetricsRead:
    return await container.metrics_service.funnel(session)


@router.get("/metrics/dashboard", response_model=MetricsDashboardRead)
async def metrics_dashboard(
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> MetricsDashboardRead:
    return await container.metrics_service.dashboard(session)


@router.get("/leads/{lead_id}/telemetry", response_model=LeadTelemetryRead)
async def lead_telemetry(
    lead_id: str,
    session: AsyncSession = Depends(get_db_session),
    container: ServiceContainer = Depends(get_container),
) -> LeadTelemetryRead:
    telemetry = await container.metrics_service.lead_telemetry(session, lead_id)
    if telemetry is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return telemetry


def _lead_read(lead: Lead) -> LeadRead:
    company = lead.company
    signals = [SignalRead.model_validate(signal) for signal in (company.signals if company else [])[:20]]
    return LeadRead(
        id=lead.id,
        status=lead.status.value,
        icp_class=lead.icp_class,
        persona_class=lead.persona_class,
        why_now=lead.why_now,
        recommended_offer=lead.recommended_offer,
        recommended_sequence=lead.recommended_sequence,
        confidence=lead.confidence,
        company=company,
        contact=lead.contact,
        scores=[
            {
                'company_fit': score.company_fit,
                'persona_fit': score.persona_fit,
                'trigger_strength': score.trigger_strength,
                'pain_fit': score.pain_fit,
                'reachability': score.reachability,
                'total_score': score.total_score,
                'lead_grade': score.lead_grade,
                'rationale': score.rationale,
                'model_confidence': score.model_confidence,
            }
            for score in lead.scores
        ],
        signals=signals,
    )


def _reply_read(reply: ReplyEvent) -> ReplyEventRead:
    lead = reply.lead
    company = lead.company if lead else None
    contact = lead.contact if lead else None
    message = reply.outreach_message
    intent_label = (reply.metadata_json or {}).get("intent_label") or {
        ReplyType.POSITIVE: "positive",
        ReplyType.NEGATIVE: "negative",
        ReplyType.NEUTRAL: "neutral",
        ReplyType.NOT_NOW: "not_now",
        ReplyType.WRONG_PERSON: "not_relevant",
        ReplyType.OOO: "out_of_office",
    }.get(reply.reply_type, reply.reply_type.value)
    time_to_reply_hours = None
    if message and message.sent_at:
        time_to_reply_hours = round(max((reply.created_at - message.sent_at).total_seconds() / 3600.0, 0.0), 2)
    return ReplyEventRead(
        id=reply.id,
        lead_id=reply.lead_id,
        outreach_message_id=reply.outreach_message_id,
        reply_type=reply.reply_type.value,
        raw_text=reply.raw_text,
        sentiment=reply.sentiment,
        metadata_json=reply.metadata_json,
        created_at=reply.created_at,
        lead_status=lead.status.value if lead else None,
        company_name=company.name if company else None,
        contact_name=contact.full_name if contact else None,
        intent_label=str(intent_label),
        sequence_id=message.sequence_id if message else None,
        sequence_key=message.sequence.sequence_key if message and message.sequence else None,
        step_number=message.step_number if message else None,
        time_to_reply_hours=time_to_reply_hours,
    )


def _coerce_delivery_event_type(value: str) -> DeliveryEventType:
    try:
        return DeliveryEventType(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid delivery event type") from exc


def _coerce_conversion_event_type(value: str) -> ConversionEventType:
    try:
        return ConversionEventType(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversion event type") from exc


def _coerce_lead_status(value: str) -> LeadStatus:
    try:
        return LeadStatus(value)
    except ValueError:
        try:
            return LeadStatus(value.lower())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid lead status") from exc
