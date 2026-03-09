from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
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
    OutreachMessage,
    OutreachSequence,
    ReplyEvent,
    ReplyType,
    SequenceStatus,
)
from outreach_app.gtm_service.schemas.lead import ReplyEventRead
from outreach_app.gtm_service.schemas.telemetry import (
    AttributionPerformanceRead,
    ConversionEventRead,
    DeliveryEventRead,
    FunnelMetricsRead,
    LeadTelemetryRead,
    MessageTelemetryRead,
    MetricsDashboardRead,
    SequencePerformanceRead,
    StepPerformanceRead,
)


class MetricsService:
    async def summary(self, session: AsyncSession) -> dict[str, Any]:
        leads_total = await session.scalar(select(func.count(Lead.id))) or 0
        active_sequences = await session.scalar(
            select(func.count(OutreachSequence.id)).where(OutreachSequence.status == SequenceStatus.ACTIVE)
        ) or 0
        sent_messages = await session.scalar(
            select(func.count(OutreachMessage.id)).where(OutreachMessage.sent_at.is_not(None))
        ) or 0
        replies_total = await session.scalar(select(func.count(ReplyEvent.id))) or 0
        positive_replies = await session.scalar(
            select(func.count(ReplyEvent.id)).where(ReplyEvent.reply_type == ReplyType.POSITIVE)
        ) or 0
        meetings_booked = await session.scalar(
            select(func.count(ConversionEvent.id)).where(ConversionEvent.event_type == ConversionEventType.MEETING_BOOKED.value)
        ) or 0
        opportunities_created = await session.scalar(
            select(func.count(ConversionEvent.id)).where(
                ConversionEvent.event_type == ConversionEventType.OPPORTUNITY_CREATED.value
            )
        ) or 0
        today_start = datetime.now(timezone.utc) - timedelta(days=1)
        positive_last_24h = await session.scalar(
            select(func.count(ReplyEvent.id)).where(
                ReplyEvent.reply_type == ReplyType.POSITIVE,
                ReplyEvent.created_at >= today_start,
            )
        ) or 0
        grade_rows = await session.execute(
            select(LeadScore.lead_grade, func.count(LeadScore.id)).group_by(LeadScore.lead_grade)
        )
        grade_counts = {grade: int(count) for grade, count in grade_rows.all()}
        status_rows = await session.execute(select(Lead.status, func.count(Lead.id)).group_by(Lead.status))
        status_counts = {status.value if hasattr(status, "value") else str(status): int(count) for status, count in status_rows.all()}

        sent_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(OutreachSequence.lead_id)
                    .join(OutreachMessage, OutreachMessage.sequence_id == OutreachSequence.id)
                    .where(OutreachMessage.sent_at.is_not(None))
                    .distinct()
                )
            ).all()
        }
        replied_lead_ids = {lead_id for (lead_id,) in (await session.execute(select(ReplyEvent.lead_id).distinct())).all()}
        positive_replied_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(ReplyEvent.lead_id).where(ReplyEvent.reply_type == ReplyType.POSITIVE).distinct()
                )
            ).all()
        }
        meeting_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(ConversionEvent.lead_id)
                    .where(ConversionEvent.event_type == ConversionEventType.MEETING_BOOKED.value)
                    .distinct()
                )
            ).all()
        }
        opportunity_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(ConversionEvent.lead_id)
                    .where(ConversionEvent.event_type == ConversionEventType.OPPORTUNITY_CREATED.value)
                    .distinct()
                )
            ).all()
        }
        latest_delivery = await self._latest_delivery_by_message(session)
        delivered_messages = sum(1 for event in latest_delivery.values() if event.event_type == DeliveryEventType.DELIVERED.value)
        bounced_messages = sum(1 for event in latest_delivery.values() if event.event_type == DeliveryEventType.BOUNCED.value)
        blocked_messages = sum(1 for event in latest_delivery.values() if event.event_type == DeliveryEventType.BLOCKED.value)
        failed_messages = sum(1 for event in latest_delivery.values() if event.event_type == DeliveryEventType.FAILED.value)

        return {
            "leads_total": int(leads_total),
            "active_sequences": int(active_sequences),
            "sent_messages": int(sent_messages),
            "delivered_messages": int(delivered_messages),
            "bounced_messages": int(bounced_messages),
            "blocked_messages": int(blocked_messages),
            "failed_messages": int(failed_messages),
            "replies_total": int(replies_total),
            "positive_replies": int(positive_replies),
            "meetings_booked": int(meetings_booked),
            "opportunities_created": int(opportunities_created),
            "reply_rate_pct": self._pct(len(replied_lead_ids), len(sent_lead_ids)),
            "positive_reply_rate_pct": self._pct(len(positive_replied_lead_ids), len(sent_lead_ids)),
            "meeting_rate_pct": self._pct(len(meeting_lead_ids), len(sent_lead_ids)),
            "opportunity_rate_pct": self._pct(len(opportunity_lead_ids), len(sent_lead_ids)),
            "grade_counts": grade_counts,
            "status_counts": status_counts,
            "positive_replies_last_24h": int(positive_last_24h),
        }

    async def sequence_performance(self, session: AsyncSession, limit: int = 50) -> list[SequencePerformanceRead]:
        sequences = await self._load_sequences(session)
        lead_sequence_counts = self._lead_sequence_counts(sequences)
        rows: dict[str, dict[str, Any]] = {}
        for sequence in sequences:
            lead = sequence.lead
            bucket = rows.setdefault(
                sequence.sequence_key,
                {
                    "sequence_ids": set(),
                    "lead_ids": set(),
                    "sent_lead_ids": set(),
                    "replying_lead_ids": set(),
                    "positive_replying_lead_ids": set(),
                    "meeting_lead_ids": set(),
                    "opportunity_lead_ids": set(),
                    "messages_total": 0,
                    "sent_messages": 0,
                    "delivered_messages": 0,
                    "bounced_messages": 0,
                    "blocked_messages": 0,
                    "failed_messages": 0,
                    "replies_total": 0,
                    "positive_replies": 0,
                    "time_to_first_reply_hours": [],
                },
            )
            bucket["sequence_ids"].add(sequence.id)
            bucket["lead_ids"].add(lead.id)
            messages = list(sequence.messages)
            bucket["messages_total"] += len(messages)
            if any(message.sent_at for message in messages):
                bucket["sent_lead_ids"].add(lead.id)

            for message in messages:
                if message.sent_at:
                    bucket["sent_messages"] += 1
                latest_delivery = self._latest_delivery_event(message.delivery_events)
                if latest_delivery:
                    if latest_delivery.event_type == DeliveryEventType.DELIVERED.value:
                        bucket["delivered_messages"] += 1
                    elif latest_delivery.event_type == DeliveryEventType.BOUNCED.value:
                        bucket["bounced_messages"] += 1
                    elif latest_delivery.event_type == DeliveryEventType.BLOCKED.value:
                        bucket["blocked_messages"] += 1
                    elif latest_delivery.event_type == DeliveryEventType.FAILED.value:
                        bucket["failed_messages"] += 1

            replies = self._sequence_replies(sequence, lead_sequence_counts.get(lead.id, 1))
            if replies:
                bucket["replying_lead_ids"].add(lead.id)
                bucket["replies_total"] += len(replies)
                positive = [reply for reply in replies if reply.reply_type == ReplyType.POSITIVE]
                if positive:
                    bucket["positive_replying_lead_ids"].add(lead.id)
                    bucket["positive_replies"] += len(positive)
                first_reply_hours = self._first_reply_hours(replies)
                if first_reply_hours is not None:
                    bucket["time_to_first_reply_hours"].append(first_reply_hours)

            conversions = self._sequence_conversions(sequence, lead_sequence_counts.get(lead.id, 1))
            if any(event.event_type == ConversionEventType.MEETING_BOOKED.value for event in conversions):
                bucket["meeting_lead_ids"].add(lead.id)
            if any(event.event_type == ConversionEventType.OPPORTUNITY_CREATED.value for event in conversions):
                bucket["opportunity_lead_ids"].add(lead.id)

        ordered = []
        for sequence_key, bucket in rows.items():
            sent_leads = len(bucket["sent_lead_ids"])
            ordered.append(
                SequencePerformanceRead(
                    sequence_key=sequence_key,
                    sequences_total=len(bucket["sequence_ids"]),
                    leads_total=len(bucket["lead_ids"]),
                    sent_leads=sent_leads,
                    messages_total=bucket["messages_total"],
                    sent_messages=bucket["sent_messages"],
                    delivered_messages=bucket["delivered_messages"],
                    bounced_messages=bucket["bounced_messages"],
                    blocked_messages=bucket["blocked_messages"],
                    failed_messages=bucket["failed_messages"],
                    replies_total=bucket["replies_total"],
                    replying_leads=len(bucket["replying_lead_ids"]),
                    positive_replies=bucket["positive_replies"],
                    positive_replying_leads=len(bucket["positive_replying_lead_ids"]),
                    meetings_booked=len(bucket["meeting_lead_ids"]),
                    opportunities_created=len(bucket["opportunity_lead_ids"]),
                    send_rate_pct=self._pct(bucket["sent_messages"], bucket["messages_total"]),
                    reply_rate_pct=self._pct(len(bucket["replying_lead_ids"]), sent_leads),
                    positive_reply_rate_pct=self._pct(len(bucket["positive_replying_lead_ids"]), sent_leads),
                    meeting_rate_pct=self._pct(len(bucket["meeting_lead_ids"]), sent_leads),
                    opportunity_rate_pct=self._pct(len(bucket["opportunity_lead_ids"]), sent_leads),
                    avg_time_to_first_reply_hours=self._avg(bucket["time_to_first_reply_hours"]),
                )
            )
        ordered.sort(key=lambda row: (-row.positive_reply_rate_pct, -row.reply_rate_pct, row.sequence_key))
        return ordered[:limit]

    async def step_performance(self, session: AsyncSession) -> list[StepPerformanceRead]:
        sequences = await self._load_sequences(session)
        bucket_by_step: dict[int, dict[str, Any]] = defaultdict(
            lambda: {
                "messages_total": 0,
                "sent_messages": 0,
                "delivered_messages": 0,
                "bounced_messages": 0,
                "blocked_messages": 0,
                "failed_messages": 0,
                "replies_total": 0,
                "messages_with_reply": 0,
                "messages_with_positive_reply": 0,
                "positive_replies": 0,
                "time_to_reply_hours": [],
            }
        )
        for sequence in sequences:
            for message in sequence.messages:
                bucket = bucket_by_step[message.step_number]
                bucket["messages_total"] += 1
                if message.sent_at:
                    bucket["sent_messages"] += 1
                latest_delivery = self._latest_delivery_event(message.delivery_events)
                if latest_delivery:
                    if latest_delivery.event_type == DeliveryEventType.DELIVERED.value:
                        bucket["delivered_messages"] += 1
                    elif latest_delivery.event_type == DeliveryEventType.BOUNCED.value:
                        bucket["bounced_messages"] += 1
                    elif latest_delivery.event_type == DeliveryEventType.BLOCKED.value:
                        bucket["blocked_messages"] += 1
                    elif latest_delivery.event_type == DeliveryEventType.FAILED.value:
                        bucket["failed_messages"] += 1
                replies = sorted(message.replies, key=lambda item: item.created_at)
                if replies:
                    bucket["messages_with_reply"] += 1
                    bucket["replies_total"] += len(replies)
                    positive = [reply for reply in replies if reply.reply_type == ReplyType.POSITIVE]
                    if positive:
                        bucket["messages_with_positive_reply"] += 1
                        bucket["positive_replies"] += len(positive)
                    if message.sent_at:
                        for reply in replies:
                            bucket["time_to_reply_hours"].append(
                                max((reply.created_at - message.sent_at).total_seconds() / 3600.0, 0.0)
                            )

        rows: list[StepPerformanceRead] = []
        previous_sent_messages: int | None = None
        for step_number in sorted(bucket_by_step):
            bucket = bucket_by_step[step_number]
            dropoff = None
            if previous_sent_messages and previous_sent_messages > 0:
                dropoff = round(max(previous_sent_messages - bucket["sent_messages"], 0) / previous_sent_messages * 100, 2)
            rows.append(
                StepPerformanceRead(
                    step_number=step_number,
                    messages_total=bucket["messages_total"],
                    sent_messages=bucket["sent_messages"],
                    delivered_messages=bucket["delivered_messages"],
                    bounced_messages=bucket["bounced_messages"],
                    blocked_messages=bucket["blocked_messages"],
                    failed_messages=bucket["failed_messages"],
                    replies_total=bucket["replies_total"],
                    positive_replies=bucket["positive_replies"],
                    reply_rate_pct=self._pct(bucket["messages_with_reply"], bucket["sent_messages"]),
                    positive_reply_rate_pct=self._pct(bucket["messages_with_positive_reply"], bucket["sent_messages"]),
                    avg_time_to_reply_hours=self._avg(bucket["time_to_reply_hours"]),
                    dropoff_from_previous_step_pct=dropoff,
                )
            )
            previous_sent_messages = bucket["sent_messages"]
        return rows

    async def attribution_breakdown(self, session: AsyncSession, limit: int = 50) -> list[AttributionPerformanceRead]:
        sequences = await self._load_sequences(session)
        lead_sequence_counts = self._lead_sequence_counts(sequences)
        rows: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "lead_ids": set(),
                "sent_lead_ids": set(),
                "replying_lead_ids": set(),
                "positive_replying_lead_ids": set(),
                "meeting_lead_ids": set(),
                "opportunity_lead_ids": set(),
            }
        )
        for sequence in sequences:
            lead = sequence.lead
            attribution = self._attribution_values(sequence)
            sent = any(message.sent_at for message in sequence.messages)
            sequence_replies = self._sequence_replies(sequence, lead_sequence_counts.get(lead.id, 1))
            replied = bool(sequence_replies)
            positive = any(reply.reply_type == ReplyType.POSITIVE for reply in sequence_replies)
            conversions = self._sequence_conversions(sequence, lead_sequence_counts.get(lead.id, 1))
            meeting = any(event.event_type == ConversionEventType.MEETING_BOOKED.value for event in conversions)
            opportunity = any(event.event_type == ConversionEventType.OPPORTUNITY_CREATED.value for event in conversions)
            for attr_type, attr_values in attribution.items():
                for attr_value in attr_values:
                    bucket = rows[(attr_type, attr_value)]
                    bucket["lead_ids"].add(lead.id)
                    if sent:
                        bucket["sent_lead_ids"].add(lead.id)
                    if replied:
                        bucket["replying_lead_ids"].add(lead.id)
                    if positive:
                        bucket["positive_replying_lead_ids"].add(lead.id)
                    if meeting:
                        bucket["meeting_lead_ids"].add(lead.id)
                    if opportunity:
                        bucket["opportunity_lead_ids"].add(lead.id)

        result = [
            AttributionPerformanceRead(
                attribution_type=attr_type,
                attribution_value=attr_value,
                leads_total=len(bucket["lead_ids"]),
                sent_leads=len(bucket["sent_lead_ids"]),
                replying_leads=len(bucket["replying_lead_ids"]),
                positive_replying_leads=len(bucket["positive_replying_lead_ids"]),
                meetings_booked=len(bucket["meeting_lead_ids"]),
                opportunities_created=len(bucket["opportunity_lead_ids"]),
                reply_rate_pct=self._pct(len(bucket["replying_lead_ids"]), len(bucket["sent_lead_ids"])),
                positive_reply_rate_pct=self._pct(
                    len(bucket["positive_replying_lead_ids"]),
                    len(bucket["sent_lead_ids"]),
                ),
                meeting_rate_pct=self._pct(len(bucket["meeting_lead_ids"]), len(bucket["sent_lead_ids"])),
                opportunity_rate_pct=self._pct(
                    len(bucket["opportunity_lead_ids"]),
                    len(bucket["sent_lead_ids"]),
                ),
            )
            for (attr_type, attr_value), bucket in rows.items()
        ]
        result.sort(key=lambda row: (-row.positive_reply_rate_pct, -row.reply_rate_pct, row.attribution_type, row.attribution_value))
        return result[:limit]

    async def funnel(self, session: AsyncSession) -> FunnelMetricsRead:
        leads = (await session.execute(select(Lead))).scalars().all()
        sent_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(OutreachSequence.lead_id)
                    .join(OutreachMessage, OutreachMessage.sequence_id == OutreachSequence.id)
                    .where(OutreachMessage.sent_at.is_not(None))
                    .distinct()
                )
            ).all()
        }
        replied_lead_ids = {lead_id for (lead_id,) in (await session.execute(select(ReplyEvent.lead_id).distinct())).all()}
        positive_replied_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(ReplyEvent.lead_id).where(ReplyEvent.reply_type == ReplyType.POSITIVE).distinct()
                )
            ).all()
        }
        meeting_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(ConversionEvent.lead_id)
                    .where(ConversionEvent.event_type == ConversionEventType.MEETING_BOOKED.value)
                    .distinct()
                )
            ).all()
        }
        opportunity_lead_ids = {
            lead_id
            for (lead_id,) in (
                await session.execute(
                    select(ConversionEvent.lead_id)
                    .where(ConversionEvent.event_type == ConversionEventType.OPPORTUNITY_CREATED.value)
                    .distinct()
                )
            ).all()
        }
        return FunnelMetricsRead(
            leads_total=len(leads),
            qualified_leads=sum(1 for lead in leads if lead.status in {LeadStatus.QUALIFIED, LeadStatus.QUEUED, LeadStatus.RESPONDED_POSITIVE, LeadStatus.RESPONDED_NEGATIVE}),
            queued_leads=sum(1 for lead in leads if lead.status in {LeadStatus.QUEUED, LeadStatus.RESPONDED_POSITIVE, LeadStatus.RESPONDED_NEGATIVE}),
            sent_leads=len(sent_lead_ids),
            replied_leads=len(replied_lead_ids),
            positive_replied_leads=len(positive_replied_lead_ids),
            meetings_booked=len(meeting_lead_ids),
            opportunities_created=len(opportunity_lead_ids),
        )

    async def lead_telemetry(self, session: AsyncSession, lead_id: str) -> LeadTelemetryRead | None:
        stmt = (
            select(Lead)
            .where(Lead.id == lead_id)
            .options(
                selectinload(Lead.company).selectinload(Company.signals),
                selectinload(Lead.contact),
                selectinload(Lead.replies).selectinload(ReplyEvent.outreach_message).selectinload(OutreachMessage.sequence),
                selectinload(Lead.conversion_events),
                selectinload(Lead.sequences)
                .selectinload(OutreachSequence.messages)
                .selectinload(OutreachMessage.delivery_events),
                selectinload(Lead.sequences)
                .selectinload(OutreachSequence.messages)
                .selectinload(OutreachMessage.replies),
            )
        )
        lead = (await session.execute(stmt)).scalars().unique().one_or_none()
        if lead is None:
            return None

        messages = [message for sequence in lead.sequences for message in sequence.messages]
        delivery_latest = {message.id: self._latest_delivery_event(message.delivery_events) for message in messages}
        counters = {
            "sent_messages": sum(1 for message in messages if message.sent_at),
            "delivered_messages": sum(
                1 for event in delivery_latest.values() if event and event.event_type == DeliveryEventType.DELIVERED.value
            ),
            "bounced_messages": sum(
                1 for event in delivery_latest.values() if event and event.event_type == DeliveryEventType.BOUNCED.value
            ),
            "blocked_messages": sum(
                1 for event in delivery_latest.values() if event and event.event_type == DeliveryEventType.BLOCKED.value
            ),
            "failed_messages": sum(
                1 for event in delivery_latest.values() if event and event.event_type == DeliveryEventType.FAILED.value
            ),
        }
        reply_reads = [self._reply_read(reply) for reply in sorted(lead.replies, key=lambda item: item.created_at, reverse=True)]
        conversion_reads = [
            self._conversion_read(event)
            for event in sorted(lead.conversion_events, key=lambda item: item.occurred_at, reverse=True)
        ]
        message_reads = []
        for sequence in sorted(lead.sequences, key=lambda item: item.created_at):
            for message in sequence.messages:
                latest_event = delivery_latest.get(message.id)
                reply_intents = [self._reply_intent(reply) for reply in sorted(message.replies, key=lambda item: item.created_at)]
                message_reads.append(
                    MessageTelemetryRead(
                        message_id=message.id,
                        sequence_id=sequence.id,
                        sequence_key=sequence.sequence_key,
                        step_number=message.step_number,
                        channel=message.channel.value,
                        subject=message.subject,
                        status=message.status.value,
                        scheduled_for=message.scheduled_for,
                        sent_at=message.sent_at,
                        latest_delivery_status=latest_event.event_type if latest_event else None,
                        latest_delivery_reason=latest_event.reason if latest_event else None,
                        delivery_events=[self._delivery_read(event) for event in message.delivery_events],
                        reply_count=len(message.replies),
                        reply_intents=reply_intents,
                    )
                )
        return LeadTelemetryRead(
            lead_id=lead.id,
            lead_status=lead.status.value,
            company_name=lead.company.name if lead.company else None,
            contact_name=lead.contact.full_name if lead.contact else None,
            recommended_sequence=lead.recommended_sequence,
            recommended_offer=lead.recommended_offer,
            persona_class=lead.persona_class,
            icp_class=lead.icp_class,
            attribution_sources=self._lead_sources(lead),
            replies_total=len(lead.replies),
            positive_replies=sum(1 for reply in lead.replies if reply.reply_type == ReplyType.POSITIVE),
            meetings_booked=sum(
                1 for event in lead.conversion_events if event.event_type == ConversionEventType.MEETING_BOOKED.value
            ),
            opportunities_created=sum(
                1
                for event in lead.conversion_events
                if event.event_type == ConversionEventType.OPPORTUNITY_CREATED.value
            ),
            messages=message_reads,
            reply_events=reply_reads,
            conversion_events=conversion_reads,
            **counters,
        )

    async def dashboard(self, session: AsyncSession) -> MetricsDashboardRead:
        recent_replies = (
            await session.execute(
                select(ReplyEvent)
                .order_by(ReplyEvent.created_at.desc())
                .limit(10)
                .options(
                    selectinload(ReplyEvent.outreach_message).selectinload(OutreachMessage.sequence),
                    selectinload(ReplyEvent.lead).selectinload(Lead.company),
                    selectinload(ReplyEvent.lead).selectinload(Lead.contact),
                )
            )
        ).scalars().all()
        recent_delivery_issues = (
            await session.execute(
                select(DeliveryEvent)
                .where(DeliveryEvent.event_type.in_([
                    DeliveryEventType.BLOCKED.value,
                    DeliveryEventType.BOUNCED.value,
                    DeliveryEventType.FAILED.value,
                ]))
                .order_by(DeliveryEvent.occurred_at.desc(), DeliveryEvent.created_at.desc())
                .limit(10)
            )
        ).scalars().all()
        recent_conversions = (
            await session.execute(
                select(ConversionEvent).order_by(ConversionEvent.occurred_at.desc(), ConversionEvent.created_at.desc()).limit(10)
            )
        ).scalars().all()
        return MetricsDashboardRead(
            summary=await self.summary(session),
            funnel=await self.funnel(session),
            sequences=await self.sequence_performance(session, limit=10),
            steps=await self.step_performance(session),
            attribution=await self.attribution_breakdown(session, limit=15),
            recent_replies=[self._reply_read(reply) for reply in recent_replies],
            recent_delivery_issues=[self._delivery_read(event) for event in recent_delivery_issues],
            recent_conversions=[self._conversion_read(event) for event in recent_conversions],
        )

    async def _load_sequences(self, session: AsyncSession) -> list[OutreachSequence]:
        stmt = (
            select(OutreachSequence)
            .options(
                selectinload(OutreachSequence.lead).selectinload(Lead.company).selectinload(Company.signals),
                selectinload(OutreachSequence.lead).selectinload(Lead.contact),
                selectinload(OutreachSequence.lead)
                .selectinload(Lead.replies)
                .selectinload(ReplyEvent.outreach_message)
                .selectinload(OutreachMessage.sequence),
                selectinload(OutreachSequence.lead).selectinload(Lead.conversion_events),
                selectinload(OutreachSequence.messages).selectinload(OutreachMessage.delivery_events),
                selectinload(OutreachSequence.messages).selectinload(OutreachMessage.replies),
            )
        )
        return list((await session.execute(stmt)).scalars().unique().all())

    async def _latest_delivery_by_message(self, session: AsyncSession) -> dict[str, DeliveryEvent]:
        rows = (
            await session.execute(select(DeliveryEvent).order_by(DeliveryEvent.occurred_at.asc(), DeliveryEvent.created_at.asc()))
        ).scalars().all()
        latest: dict[str, DeliveryEvent] = {}
        for row in rows:
            latest[row.outreach_message_id] = row
        return latest

    def _sequence_replies(self, sequence: OutreachSequence, total_sequences_for_lead: int) -> list[ReplyEvent]:
        lead = sequence.lead
        message_ids = {message.id for message in sequence.messages}
        linked = [reply for reply in lead.replies if reply.outreach_message_id in message_ids]
        if linked:
            return linked
        if total_sequences_for_lead == 1:
            return list(lead.replies)
        return []

    def _sequence_conversions(self, sequence: OutreachSequence, total_sequences_for_lead: int) -> list[ConversionEvent]:
        lead = sequence.lead
        linked = [event for event in lead.conversion_events if event.sequence_id == sequence.id]
        if linked:
            return linked
        if total_sequences_for_lead == 1:
            return [event for event in lead.conversion_events if event.sequence_id is None]
        return []

    def _lead_sequence_counts(self, sequences: list[OutreachSequence]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for sequence in sequences:
            counts[sequence.lead_id] += 1
        return counts

    def _attribution_values(self, sequence: OutreachSequence) -> dict[str, list[str]]:
        metadata = sequence.metadata_json or {}
        lead = sequence.lead
        return {
            "source": metadata.get("source_labels") or self._lead_sources(lead) or ["unknown"],
            "persona": [metadata.get("persona_class") or lead.persona_class or "unknown"],
            "offer": [metadata.get("recommended_offer") or lead.recommended_offer or "unknown"],
        }

    def _lead_sources(self, lead: Lead) -> list[str]:
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

    def _reply_read(self, reply: ReplyEvent) -> ReplyEventRead:
        message = reply.outreach_message
        lead = reply.lead
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
            metadata_json=reply.metadata_json or {},
            created_at=reply.created_at,
            lead_status=lead.status.value if lead else None,
            company_name=lead.company.name if lead and lead.company else None,
            contact_name=lead.contact.full_name if lead and lead.contact else None,
            intent_label=self._reply_intent(reply),
            sequence_id=message.sequence_id if message else None,
            sequence_key=message.sequence.sequence_key if message and message.sequence else None,
            step_number=message.step_number if message else None,
            time_to_reply_hours=time_to_reply_hours,
        )

    def _delivery_read(self, event: DeliveryEvent) -> DeliveryEventRead:
        return DeliveryEventRead.model_validate(event)

    def _conversion_read(self, event: ConversionEvent) -> ConversionEventRead:
        return ConversionEventRead.model_validate(event)

    def _reply_intent(self, reply: ReplyEvent) -> str:
        explicit = (reply.metadata_json or {}).get("intent_label")
        if explicit:
            return str(explicit)
        return {
            ReplyType.POSITIVE: "positive",
            ReplyType.NEGATIVE: "negative",
            ReplyType.NEUTRAL: "neutral",
            ReplyType.NOT_NOW: "not_now",
            ReplyType.WRONG_PERSON: "not_relevant",
            ReplyType.OOO: "out_of_office",
        }.get(reply.reply_type, reply.reply_type.value)

    def _latest_delivery_event(self, events: list[DeliveryEvent]) -> DeliveryEvent | None:
        latest = None
        for event in events:
            if latest is None or (event.occurred_at, event.created_at) >= (latest.occurred_at, latest.created_at):
                latest = event
        return latest

    def _first_reply_hours(self, replies: list[ReplyEvent]) -> float | None:
        first = min(replies, key=lambda item: item.created_at, default=None)
        if first is None or first.outreach_message is None or first.outreach_message.sent_at is None:
            return None
        return round(max((first.created_at - first.outreach_message.sent_at).total_seconds() / 3600.0, 0.0), 2)

    def _pct(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator * 100, 2)

    def _avg(self, values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 2)
