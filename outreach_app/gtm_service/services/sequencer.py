from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.db.models import (
    Company,
    Contact,
    DeliveryEvent,
    DeliveryEventType,
    Lead,
    LeadStatus,
    MessageStatus,
    OutreachChannel,
    OutreachMessage,
    OutreachSequence,
    SequenceStatus,
)
from outreach_app.gtm_service.schemas.outreach import RunDueResponse
from outreach_app.gtm_service.services.mailer import EmailDeliveryService, LinkedInDispatchService
from outreach_app.gtm_service.services.outreach import OutreachGenerator
from outreach_app.gtm_service.services.research import ResearchOutput

if TYPE_CHECKING:
    from outreach_app.gtm_service.services.crm import SheetsCRMService


class SequenceService:
    def __init__(
        self,
        settings: Settings,
        mailer: EmailDeliveryService,
        linkedin_dispatch: LinkedInDispatchService,
        outreach_generator: OutreachGenerator,
        crm_sync_service: SheetsCRMService | None = None,
    ) -> None:
        self.settings = settings
        self.mailer = mailer
        self.linkedin_dispatch = linkedin_dispatch
        self.outreach_generator = outreach_generator
        self.crm_sync_service = crm_sync_service

    async def queue_lead(
        self,
        session: AsyncSession,
        *,
        lead_id: str,
        force: bool = False,
        start_immediately: bool = False,
        partner_name: str | None = None,
    ) -> OutreachSequence:
        lead = await self._get_lead(session, lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")
        if not lead.company:
            raise ValueError("Lead has no company")
        if not lead.recommended_sequence:
            raise ValueError("Lead has no recommended sequence")

        existing = next((seq for seq in lead.sequences if seq.status in {SequenceStatus.DRAFT, SequenceStatus.ACTIVE}), None)
        if existing and not force:
            return existing
        if existing and force:
            existing.status = SequenceStatus.STOPPED
            for message in existing.messages:
                if message.status == MessageStatus.QUEUED:
                    message.status = MessageStatus.SKIPPED

        research = ResearchOutput(
            icp_class=lead.icp_class or "ai_bio_startup",
            persona_class=lead.persona_class or "founder",
            why_now=lead.why_now or [],
            pain_hypotheses=[],
            offer_recommendation=lead.recommended_offer or "Standard run",
            sequence_recommendation=lead.recommended_sequence,
            proof_angle="",
            trigger_line=(lead.why_now[0] if lead.why_now else f"{lead.company.name} is active"),
            trigger_short=(lead.why_now[0] if lead.why_now else f"{lead.company.name} is active"),
            partner_intro="A partner thought this might be relevant.",
            extracted_signals=[],
            confidence=lead.confidence,
        )
        preview = self.outreach_generator.preview_sequence(
            sequence_key=lead.recommended_sequence,
            company_name=lead.company.name,
            contact_first_name=(lead.contact.first_name if lead.contact else None),
            research=research,
            now=datetime.now(timezone.utc),
            partner_name=partner_name,
        )
        anchor = datetime.now(timezone.utc)
        sequence = OutreachSequence(
            lead_id=lead.id,
            sequence_key=preview.sequence_key,
            status=SequenceStatus.ACTIVE,
            current_step=0,
            started_at=anchor if start_immediately else None,
            last_action_at=None,
            metadata_json={"auto_generated": True},
        )
        sequence.metadata_json = {
            **sequence.metadata_json,
            "icp_class": lead.icp_class,
            "persona_class": lead.persona_class,
            "recommended_offer": lead.recommended_offer,
            "recommended_sequence": lead.recommended_sequence,
            "source_labels": self._lead_source_labels(lead),
            "company_name": lead.company.name,
            "contact_name": lead.contact.full_name if lead.contact else None,
        }
        session.add(sequence)
        await session.flush()

        for generated in preview.messages:
            scheduled_for = anchor + timedelta(days=generated.delay_days)
            message = OutreachMessage(
                sequence_id=sequence.id,
                step_number=generated.step_number,
                channel=OutreachChannel(generated.channel),
                subject=generated.subject,
                body=generated.body,
                status=MessageStatus.QUEUED,
                scheduled_for=scheduled_for,
                metadata_json=generated.metadata_json,
            )
            session.add(message)
        lead.status = LeadStatus.QUEUED
        await session.commit()
        await session.refresh(sequence)
        if self.crm_sync_service and self.crm_sync_service.enabled:
            latest_score = max(lead.scores, key=lambda item: item.created_at) if lead.scores else None
            self.crm_sync_service.sync_lead_snapshot(
                company=lead.company,
                contact=lead.contact,
                lead=lead,
                score=latest_score,
            )
        return sequence

    async def run_due_messages(self, session: AsyncSession) -> RunDueResponse:
        now = datetime.now(timezone.utc)
        stmt = (
            select(OutreachMessage)
            .where(and_(OutreachMessage.status == MessageStatus.QUEUED, OutreachMessage.scheduled_for <= now))
            .order_by(OutreachMessage.scheduled_for.asc(), OutreachMessage.created_at.asc())
            .options(
                selectinload(OutreachMessage.sequence)
                .selectinload(OutreachSequence.lead)
                .selectinload(Lead.company),
                selectinload(OutreachMessage.sequence)
                .selectinload(OutreachSequence.lead)
                .selectinload(Lead.contact),
                selectinload(OutreachMessage.sequence)
                .selectinload(OutreachSequence.lead)
                .selectinload(Lead.replies),
                selectinload(OutreachMessage.sequence).selectinload(OutreachSequence.messages),
            )
        )
        due_messages = list((await session.execute(stmt)).scalars().unique().all())

        sent = queued_manual = failed = 0
        details: list[dict[str, Any]] = []
        sheet_sync_events: list[tuple[DeliveryEvent, Lead, OutreachSequence, OutreachMessage, Company | None, Contact | None]] = []

        for message in due_messages:
            sequence = message.sequence
            lead = sequence.lead
            contact = lead.contact
            company = lead.company
            if lead.status in {LeadStatus.RESPONDED_POSITIVE, LeadStatus.RESPONDED_NEGATIVE, LeadStatus.DISQUALIFIED}:
                message.status = MessageStatus.SKIPPED
                details.append({"message_id": message.id, "status": "skipped", "reason": lead.status.value})
                continue
            try:
                if message.channel == OutreachChannel.EMAIL:
                    if not contact or not contact.email:
                        raise ValueError("Lead has no email address")
                    provider_id = await self.mailer.send_email(
                        to_email=contact.email,
                        subject=message.subject or f"Glassbox for {company.name if company else 'your team'}",
                        body=message.body,
                        metadata={"lead_id": lead.id, "sequence_id": sequence.id, "message_id": message.id},
                    )
                    message.provider_message_id = provider_id
                    message.status = MessageStatus.SENT
                    message.sent_at = now
                    delivery_event = self._delivery_event(
                        message=message,
                        lead=lead,
                        event_type=DeliveryEventType.SENT,
                        occurred_at=now,
                        provider_event_id=provider_id,
                        metadata_json={"channel": "email"},
                    )
                    session.add(delivery_event)
                    sheet_sync_events.append((delivery_event, lead, sequence, message, company, contact))
                    sent += 1
                    details.append({"message_id": message.id, "status": "sent", "channel": "email"})
                elif message.channel == OutreachChannel.LINKEDIN:
                    if not contact or not contact.linkedin_url:
                        message.status = MessageStatus.AWAITING_MANUAL
                        message.metadata_json = {**message.metadata_json, "reason": "No LinkedIn URL"}
                        delivery_event = self._delivery_event(
                            message=message,
                            lead=lead,
                            event_type=DeliveryEventType.BLOCKED,
                            occurred_at=now,
                            reason="No LinkedIn URL",
                            metadata_json={"channel": "linkedin"},
                        )
                        session.add(delivery_event)
                        sheet_sync_events.append((delivery_event, lead, sequence, message, company, contact))
                        queued_manual += 1
                        details.append({"message_id": message.id, "status": "awaiting_manual", "reason": "No LinkedIn URL"})
                    else:
                        provider_id, extra = await self.linkedin_dispatch.dispatch(
                            payload={
                                "lead_id": lead.id,
                                "contact_name": contact.full_name or contact.first_name or "",
                                "company_name": company.name if company else "",
                                "linkedin_url": contact.linkedin_url,
                                "message": message.body,
                                "step_number": message.step_number,
                            }
                        )
                        message.provider_message_id = provider_id
                        message.metadata_json = {**message.metadata_json, **extra}
                        message.sent_at = now if provider_id != "manual" else None
                        message.status = MessageStatus.SENT if provider_id != "manual" else MessageStatus.AWAITING_MANUAL
                        if provider_id == "manual":
                            delivery_event = self._delivery_event(
                                message=message,
                                lead=lead,
                                event_type=DeliveryEventType.BLOCKED,
                                occurred_at=now,
                                reason="LinkedIn dispatch requires manual action",
                                provider_event_id=provider_id,
                                metadata_json={"channel": "linkedin", **extra},
                            )
                            session.add(delivery_event)
                            sheet_sync_events.append((delivery_event, lead, sequence, message, company, contact))
                            queued_manual += 1
                            details.append({"message_id": message.id, "status": "awaiting_manual", "channel": "linkedin"})
                        else:
                            delivery_event = self._delivery_event(
                                message=message,
                                lead=lead,
                                event_type=DeliveryEventType.SENT,
                                occurred_at=now,
                                provider_event_id=provider_id,
                                metadata_json={"channel": "linkedin", **extra},
                            )
                            session.add(delivery_event)
                            sheet_sync_events.append((delivery_event, lead, sequence, message, company, contact))
                            sent += 1
                            details.append({"message_id": message.id, "status": "sent", "channel": "linkedin"})
                else:
                    raise ValueError(f"Unsupported channel: {message.channel}")
            except Exception as exc:
                message.status = MessageStatus.FAILED
                message.metadata_json = {**message.metadata_json, "error": str(exc)}
                delivery_event = self._delivery_event(
                    message=message,
                    lead=lead,
                    event_type=DeliveryEventType.FAILED,
                    occurred_at=now,
                    reason=str(exc),
                    metadata_json={"channel": message.channel.value},
                )
                session.add(delivery_event)
                sheet_sync_events.append((delivery_event, lead, sequence, message, company, contact))
                failed += 1
                details.append({"message_id": message.id, "status": "failed", "error": str(exc)})
            sequence.current_step = max(sequence.current_step, message.step_number)
            sequence.last_action_at = now
            if self._sequence_done(sequence):
                sequence.status = SequenceStatus.COMPLETED
        await session.commit()
        if self.crm_sync_service and self.crm_sync_service.enabled:
            for delivery_event, lead, sequence, message, company, contact in sheet_sync_events:
                self.crm_sync_service.sync_delivery_event_record(
                    event=delivery_event,
                    lead=lead,
                    sequence=sequence,
                    message=message,
                    company=company,
                    contact=contact,
                )
        return RunDueResponse(sent=sent, queued_manual=queued_manual, failed=failed, details=details)

    async def stop_active_sequences_for_lead(self, session: AsyncSession, lead_id: str) -> None:
        stmt = (
            select(OutreachSequence)
            .where(and_(OutreachSequence.lead_id == lead_id, OutreachSequence.status == SequenceStatus.ACTIVE))
            .options(selectinload(OutreachSequence.messages))
        )
        sequences = list((await session.execute(stmt)).scalars().unique().all())
        for sequence in sequences:
            sequence.status = SequenceStatus.STOPPED
            for message in sequence.messages:
                if message.status == MessageStatus.QUEUED:
                    message.status = MessageStatus.SKIPPED
        await session.commit()

    async def _get_lead(self, session: AsyncSession, lead_id: str) -> Lead | None:
        stmt = (
            select(Lead)
            .where(Lead.id == lead_id)
            .options(
                selectinload(Lead.company),
                selectinload(Lead.company).selectinload(Company.signals),
                selectinload(Lead.contact),
                selectinload(Lead.scores),
                selectinload(Lead.replies),
                selectinload(Lead.sequences).selectinload(OutreachSequence.messages),
            )
        )
        return (await session.execute(stmt)).scalars().unique().one_or_none()

    def _sequence_done(self, sequence: OutreachSequence) -> bool:
        terminal = {MessageStatus.SENT, MessageStatus.FAILED, MessageStatus.SKIPPED, MessageStatus.AWAITING_MANUAL}
        return all(message.status in terminal for message in sequence.messages)

    def _lead_source_labels(self, lead: Lead) -> list[str]:
        company = lead.company
        if company is None:
            return []
        labels: list[str] = []
        for signal in company.signals:
            if signal.source:
                labels.append(signal.source)
            feed_title = (signal.metadata_json or {}).get("feed_title")
            if feed_title:
                labels.append(str(feed_title))
        deduped = list(dict.fromkeys(item.strip() for item in labels if item and item.strip()))
        return deduped[:8]

    def _delivery_event(
        self,
        *,
        message: OutreachMessage,
        lead: Lead,
        event_type: DeliveryEventType,
        occurred_at: datetime,
        provider_event_id: str | None = None,
        reason: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> DeliveryEvent:
        return DeliveryEvent(
            outreach_message_id=message.id,
            lead_id=lead.id,
            event_type=event_type.value,
            provider_event_id=provider_event_id,
            reason=reason,
            metadata_json=metadata_json or {},
            occurred_at=occurred_at,
        )
