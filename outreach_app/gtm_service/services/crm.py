from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.db.models import (
    Company,
    Contact,
    ConversionEvent,
    DeliveryEvent,
    Lead,
    LeadScore,
    OutreachMessage,
    OutreachSequence,
    ReplyEvent,
    ReplyType,
)
from outreach_app.gtm_service.services.text_utils import full_name

if TYPE_CHECKING:
    from outreach_app.gtm_service.services.metrics import MetricsService


class SheetsCRMService:
    LEAD_HEADERS = [
        "lead_id",
        "updated_at",
        "company_id",
        "company_name",
        "firm",
        "company_domain",
        "company_website",
        "official_url",
        "company_industry",
        "firm_type",
        "contact_id",
        "contact_name",
        "person",
        "contact_email",
        "contact_title",
        "priority_bucket",
        "priority_score",
        "lead_status",
        "lead_grade",
        "total_score",
        "recommended_sequence",
        "recommended_offer",
        "persona_class",
        "icp_class",
        "why_now",
        "why_relevant_for_glassbox",
        "public_signal",
        "best_entry_route",
        "last_verified",
        "stage_fit",
        "public_focus",
        "selected_public_examples",
        "firm_signal",
        "why_fit_for_glassbox",
        "suggested_pitch_angle",
        "intro_path_recommendation",
        "cold_outbound_viability",
        "official_profile_url",
        "crm_status",
        "next_step",
        "internal_notes",
        "source_labels",
    ]
    LEAD_HEADER_ALIASES = {
        "lead_id": {"lead_id", "lead id", "leadid", "id"},
        "created_at": {"created_at", "created at"},
        "updated_at": {"updated_at", "updated at", "last_updated", "last updated", "modified_at", "modified at"},
        "source": {"source", "lead_source", "lead source"},
        "company_id": {"company_id", "company id"},
        "company_name": {"company_name", "company name", "account_name", "account name", "company"},
        "firm": {"firm", "company_name", "company name", "account_name", "account name"},
        "company_domain": {"company_domain", "company domain", "domain", "website_domain", "website domain"},
        "company_website": {"company_website", "company website", "website", "company_url", "company url"},
        "official_url": {"official_url", "official url", "company_website", "company website", "website"},
        "company_industry": {"company_industry", "company industry", "industry"},
        "firm_type": {"firm_type", "firm type", "company_industry", "company industry"},
        "contact_id": {"contact_id", "contact id", "person_id", "person id"},
        "contact_name": {"contact_name", "contact name", "full_name", "full name", "name"},
        "person": {"person", "contact_name", "contact name", "full_name", "full name", "name"},
        "first_name": {"first_name", "first name"},
        "last_name": {"last_name", "last name"},
        "contact_email": {"contact_email", "contact email", "email", "email_address", "email address", "work_email", "work email"},
        "contact_title": {"contact_title", "contact title", "title", "job_title", "job title", "role"},
        "country": {"country"},
        "raw_inbound_text": {"raw_inbound_text", "raw inbound text"},
        "normalized_summary": {"normalized_summary", "normalized summary", "summary"},
        "owner": {"owner"},
        "fit_score": {"fit_score", "fit score"},
        "intent_score": {"intent_score", "intent score"},
        "timing_score": {"timing_score", "timing score"},
        "priority_score": {"priority_score", "priority score"},
        "priority_bucket": {"priority_bucket", "priority bucket"},
        "lead_status": {"lead_status", "lead status", "status"},
        "lead_grade": {"lead_grade", "lead grade", "grade"},
        "total_score": {"total_score", "total score", "score"},
        "recommended_sequence": {"recommended_sequence", "recommended sequence", "sequence", "sequence_key", "sequence key"},
        "recommended_offer": {"recommended_offer", "recommended offer", "offer"},
        "persona_class": {"persona_class", "persona class", "persona"},
        "icp_class": {"icp_class", "icp class", "icp"},
        "why_now": {"why_now", "why now", "trigger", "trigger reason"},
        "why_relevant_for_glassbox": {"why_relevant_for_glassbox", "why relevant for glassbox"},
        "public_signal": {"public_signal", "public signal"},
        "best_entry_route": {"best_entry_route", "best entry route"},
        "last_verified": {"last_verified", "last verified"},
        "stage_fit": {"stage_fit", "stage fit"},
        "public_focus": {"public_focus", "public focus"},
        "selected_public_examples": {"selected_public_examples", "selected public examples"},
        "firm_signal": {"firm_signal", "firm signal"},
        "why_fit_for_glassbox": {"why_fit_for_glassbox", "why fit for glassbox"},
        "suggested_pitch_angle": {"suggested_pitch_angle", "suggested pitch angle"},
        "intro_path_recommendation": {"intro_path_recommendation", "intro path recommendation"},
        "cold_outbound_viability": {"cold_outbound_viability", "cold outbound viability"},
        "official_profile_url": {"official_profile_url", "official profile url"},
        "crm_status": {"crm_status", "crm status"},
        "next_step": {"next_step", "next step"},
        "internal_notes": {"internal_notes", "internal notes"},
        "source_labels": {"source_labels", "source labels", "source", "sources", "lead_source", "lead source"},
        "next_action": {"next_action", "next action", "next_step", "next step"},
        "next_action_due": {"next_action_due", "next action due"},
        "last_touch_at": {"last_touch_at", "last touch at"},
        "last_ai_hash": {"last_ai_hash", "last ai hash"},
        "needs_review": {"needs_review", "needs review"},
        "validation_errors": {"validation_errors", "validation errors"},
        "latest_followup_draft_id": {"latest_followup_draft_id", "latest followup draft id"},
    }
    LEAD_MATCH_PRIORITY = ["lead_id", "contact_email", "company_domain", "company_name", "contact_name"]
    ACCOUNT_HEADERS = [
        "account_id",
        "created_at",
        "updated_at",
        "domain",
        "account_name",
        "industry",
        "size_band",
        "tier",
        "owner",
        "account_brief",
        "pain_points",
        "proof_points",
        "champion",
        "risk_flags",
        "health_score",
        "last_ai_hash",
    ]
    ACCOUNT_HEADER_ALIASES = {
        "account_id": {"account_id", "account id", "company_id", "company id"},
        "created_at": {"created_at", "created at"},
        "updated_at": {"updated_at", "updated at"},
        "domain": {"domain", "company_domain", "company domain"},
        "account_name": {"account_name", "account name", "company_name", "company name", "company"},
        "industry": {"industry", "company_industry", "company industry"},
        "size_band": {"size_band", "size band"},
        "tier": {"tier", "lead_grade", "lead grade"},
        "owner": {"owner"},
        "account_brief": {"account_brief", "account brief", "normalized_summary", "normalized summary"},
        "pain_points": {"pain_points", "pain points", "why_now", "why now"},
        "proof_points": {"proof_points", "proof points", "source_labels", "source labels"},
        "champion": {"champion", "contact_name", "contact name"},
        "risk_flags": {"risk_flags", "risk flags"},
        "health_score": {"health_score", "health score", "total_score", "total score"},
        "last_ai_hash": {"last_ai_hash", "last ai hash"},
    }
    ACCOUNT_MATCH_PRIORITY = ["account_id", "domain", "account_name"]
    CONTACT_HEADERS = [
        "contact_id",
        "created_at",
        "updated_at",
        "account_id",
        "name",
        "email",
        "title",
        "role_type",
        "persona",
        "linkedin_url",
        "influence_score",
    ]
    CONTACT_HEADER_ALIASES = {
        "contact_id": {"contact_id", "contact id"},
        "created_at": {"created_at", "created at"},
        "updated_at": {"updated_at", "updated at"},
        "account_id": {"account_id", "account id", "company_id", "company id"},
        "name": {"name", "contact_name", "contact name", "full_name", "full name"},
        "email": {"email", "contact_email", "contact email", "email_address", "email address"},
        "title": {"title", "contact_title", "contact title", "job_title", "job title"},
        "role_type": {"role_type", "role type", "role", "function", "seniority"},
        "persona": {"persona", "persona_class", "persona class"},
        "linkedin_url": {"linkedin_url", "linkedin url"},
        "influence_score": {"influence_score", "influence score"},
    }
    CONTACT_MATCH_PRIORITY = ["contact_id", "email", "name"]
    ACTIVITY_HEADERS = [
        "activity_id",
        "created_at",
        "entity_type",
        "entity_id",
        "channel",
        "direction",
        "timestamp",
        "subject",
        "snippet",
        "source_ref",
        "sentiment",
        "intent_tag",
        "metadata_json",
    ]
    DEAL_HEADERS = [
        "deal_id",
        "created_at",
        "updated_at",
        "account_id",
        "primary_contact_id",
        "owner",
        "stage",
        "amount",
        "close_date",
        "probability",
        "next_step",
        "next_step_due",
        "stall_reason",
        "risk_flags",
        "risk_score",
        "health_score",
        "last_activity_at",
        "ai_stage_recommendation",
        "last_ai_hash",
        "needs_review",
        "validation_errors",
    ]
    DEAL_HEADER_ALIASES = {
        "deal_id": {"deal_id", "deal id", "external_ref", "external ref"},
        "created_at": {"created_at", "created at"},
        "updated_at": {"updated_at", "updated at"},
        "account_id": {"account_id", "account id"},
        "primary_contact_id": {"primary_contact_id", "primary contact id", "contact_id", "contact id"},
        "owner": {"owner"},
        "stage": {"stage"},
        "amount": {"amount", "value"},
        "close_date": {"close_date", "close date"},
        "probability": {"probability"},
        "next_step": {"next_step", "next step"},
        "next_step_due": {"next_step_due", "next step due"},
        "stall_reason": {"stall_reason", "stall reason"},
        "risk_flags": {"risk_flags", "risk flags"},
        "risk_score": {"risk_score", "risk score"},
        "health_score": {"health_score", "health score"},
        "last_activity_at": {"last_activity_at", "last activity at"},
        "ai_stage_recommendation": {"ai_stage_recommendation", "ai stage recommendation"},
        "last_ai_hash": {"last_ai_hash", "last ai hash"},
        "needs_review": {"needs_review", "needs review"},
        "validation_errors": {"validation_errors", "validation errors"},
    }
    DEAL_MATCH_PRIORITY = ["deal_id", "account_id"]
    REPLY_HEADERS = [
        "reply_id",
        "created_at",
        "lead_id",
        "sequence_id",
        "sequence_key",
        "outreach_message_id",
        "step_number",
        "reply_type",
        "intent_label",
        "sentiment",
        "lead_status",
        "company_name",
        "contact_name",
        "time_to_reply_hours",
        "raw_text",
        "metadata_json",
    ]
    DELIVERY_HEADERS = [
        "delivery_event_id",
        "occurred_at",
        "lead_id",
        "sequence_id",
        "sequence_key",
        "outreach_message_id",
        "step_number",
        "channel",
        "message_status",
        "event_type",
        "provider_event_id",
        "reason",
        "company_name",
        "contact_name",
        "metadata_json",
    ]
    CONVERSION_HEADERS = [
        "conversion_event_id",
        "occurred_at",
        "lead_id",
        "sequence_id",
        "sequence_key",
        "reply_event_id",
        "event_type",
        "value",
        "external_ref",
        "company_name",
        "contact_name",
        "recommended_offer",
        "persona_class",
        "metadata_json",
    ]
    METRICS_HEADERS = ["metric", "value", "synced_at"]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._service = None
        self._sheet_titles: set[str] | None = None

    async def close(self) -> None:
        self._service = None

    @property
    def enabled(self) -> bool:
        return self.settings.crm_sync_ready

    async def sync(self, *, company: Company, contact: Contact | None, lead: Lead, score: LeadScore | None) -> dict[str, Any]:
        if not self.enabled:
            return {}
        return self.sync_lead_snapshot(company=company, contact=contact, lead=lead, score=score)

    def sync_lead_snapshot(
        self,
        *,
        company: Company,
        contact: Contact | None,
        lead: Lead,
        score: LeadScore | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        record = self._lead_record(company=company, contact=contact, lead=lead, score=score)
        result = self._upsert_lead_record(
            range_a1=self.settings.crm_sheet_range_a1,
            record=record,
        )
        self.sync_account_snapshot(company=company, contact=contact, lead=lead, score=score)
        if contact is not None:
            self.sync_contact_snapshot(company=company, contact=contact, lead=lead, score=score)
        result["sheet_type"] = "lead_snapshot"
        return result

    def sync_account_snapshot(
        self,
        *,
        company: Company,
        contact: Contact | None,
        lead: Lead,
        score: LeadScore | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        record = self._account_record(company=company, contact=contact, lead=lead, score=score)
        result = self._upsert_record(
            range_a1=self.settings.crm_sheet_accounts_range_a1,
            record=record,
            default_headers=self.ACCOUNT_HEADERS,
            aliases=self.ACCOUNT_HEADER_ALIASES,
            match_priority=self.ACCOUNT_MATCH_PRIORITY,
        )
        result["sheet_type"] = "account_snapshot"
        return result

    def sync_contact_snapshot(
        self,
        *,
        company: Company,
        contact: Contact,
        lead: Lead,
        score: LeadScore | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        record = self._contact_record(company=company, contact=contact, lead=lead, score=score)
        result = self._upsert_record(
            range_a1=self.settings.crm_sheet_contacts_range_a1,
            record=record,
            default_headers=self.CONTACT_HEADERS,
            aliases=self.CONTACT_HEADER_ALIASES,
            match_priority=self.CONTACT_MATCH_PRIORITY,
        )
        result["sheet_type"] = "contact_snapshot"
        return result

    def sync_reply_record(
        self,
        *,
        reply: ReplyEvent,
        lead: Lead,
        message: OutreachMessage | None,
        company: Company | None,
        contact: Contact | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        row = self._reply_row(reply=reply, lead=lead, message=message, company=company, contact=contact)
        result = self._append_row(
            range_a1=self.settings.crm_sheet_replies_range_a1,
            headers=self.REPLY_HEADERS,
            row=row,
        )
        self._append_activity_row(
            self._activity_row_from_reply(
                reply=reply,
                lead=lead,
                message=message,
                company=company,
                contact=contact,
            )
        )
        result["sheet_type"] = "reply_event"
        return result

    def sync_delivery_event_record(
        self,
        *,
        event: DeliveryEvent,
        lead: Lead,
        sequence: OutreachSequence | None,
        message: OutreachMessage,
        company: Company | None,
        contact: Contact | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        row = self._delivery_row(
            event=event,
            lead=lead,
            sequence=sequence,
            message=message,
            company=company,
            contact=contact,
        )
        result = self._append_row(
            range_a1=self.settings.crm_sheet_delivery_events_range_a1,
            headers=self.DELIVERY_HEADERS,
            row=row,
        )
        self._append_activity_row(
            self._activity_row_from_delivery(
                event=event,
                lead=lead,
                sequence=sequence,
                message=message,
                company=company,
                contact=contact,
            )
        )
        result["sheet_type"] = "delivery_event"
        return result

    def sync_conversion_event_record(
        self,
        *,
        event: ConversionEvent,
        lead: Lead,
        sequence: OutreachSequence | None,
        company: Company | None,
        contact: Contact | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        row = self._conversion_row(
            event=event,
            lead=lead,
            sequence=sequence,
            company=company,
            contact=contact,
        )
        result = self._append_row(
            range_a1=self.settings.crm_sheet_conversion_events_range_a1,
            headers=self.CONVERSION_HEADERS,
            row=row,
        )
        self._upsert_record(
            range_a1=self.settings.crm_sheet_deals_range_a1,
            record=self._deal_record(
                event=event,
                lead=lead,
                sequence=sequence,
                company=company,
                contact=contact,
            ),
            default_headers=self.DEAL_HEADERS,
            aliases=self.DEAL_HEADER_ALIASES,
            match_priority=self.DEAL_MATCH_PRIORITY,
        )
        self._append_activity_row(
            self._activity_row_from_conversion(
                event=event,
                lead=lead,
                sequence=sequence,
                company=company,
                contact=contact,
            )
        )
        result["sheet_type"] = "conversion_event"
        return result

    async def sync_metrics_snapshot(self, *, session: AsyncSession, metrics_service: MetricsService) -> dict[str, Any]:
        if not self.enabled:
            return {}
        summary = await metrics_service.summary(session)
        timestamp = datetime.now(timezone.utc).isoformat()
        rows = [self.METRICS_HEADERS] + [[key, self._scalar(value), timestamp] for key, value in summary.items()]
        response = self._replace_table(self.settings.crm_sheet_metrics_range_a1, rows)
        return {
            "spreadsheet_id": self.settings.crm_sheet_spreadsheet_id,
            "sheet_range": self.settings.crm_sheet_metrics_range_a1,
            "sheet_type": "metrics_snapshot",
            "updated_cells": response.get("updatedCells"),
        }

    async def full_sync(self, *, session: AsyncSession, metrics_service: MetricsService) -> dict[str, Any]:
        if not self.enabled:
            return {}

        lead_stmt = (
            select(Lead)
            .order_by(Lead.updated_at.asc(), Lead.created_at.asc())
            .options(
                selectinload(Lead.company).selectinload(Company.signals),
                selectinload(Lead.contact),
                selectinload(Lead.scores),
            )
        )
        reply_stmt = (
            select(ReplyEvent)
            .order_by(ReplyEvent.created_at.asc())
            .options(
                selectinload(ReplyEvent.lead).selectinload(Lead.company),
                selectinload(ReplyEvent.lead).selectinload(Lead.contact),
                selectinload(ReplyEvent.outreach_message).selectinload(OutreachMessage.sequence),
            )
        )
        delivery_stmt = (
            select(DeliveryEvent)
            .order_by(DeliveryEvent.occurred_at.asc(), DeliveryEvent.created_at.asc())
            .options(
                selectinload(DeliveryEvent.outreach_message).selectinload(OutreachMessage.sequence).selectinload(OutreachSequence.lead).selectinload(Lead.company),
                selectinload(DeliveryEvent.outreach_message).selectinload(OutreachMessage.sequence).selectinload(OutreachSequence.lead).selectinload(Lead.contact),
            )
        )
        conversion_stmt = (
            select(ConversionEvent)
            .order_by(ConversionEvent.occurred_at.asc(), ConversionEvent.created_at.asc())
            .options(
                selectinload(ConversionEvent.lead).selectinload(Lead.company),
                selectinload(ConversionEvent.lead).selectinload(Lead.contact),
                selectinload(ConversionEvent.sequence),
            )
        )

        leads = list((await session.execute(lead_stmt)).scalars().unique().all())
        replies = list((await session.execute(reply_stmt)).scalars().unique().all())
        deliveries = list((await session.execute(delivery_stmt)).scalars().unique().all())
        conversions = list((await session.execute(conversion_stmt)).scalars().unique().all())

        lead_headers = self._merge_headers(self._existing_headers(self.settings.crm_sheet_range_a1), self.LEAD_HEADERS)
        account_headers = self._merge_headers(self._existing_headers(self.settings.crm_sheet_accounts_range_a1), self.ACCOUNT_HEADERS)
        contact_headers = self._merge_headers(self._existing_headers(self.settings.crm_sheet_contacts_range_a1), self.CONTACT_HEADERS)
        deal_headers = self._merge_headers(self._existing_headers(self.settings.crm_sheet_deals_range_a1), self.DEAL_HEADERS)
        lead_rows = [lead_headers]
        account_rows = [account_headers]
        contact_rows = [contact_headers]
        for lead in leads:
            score = self._latest_score(lead)
            lead_rows.append(
                self._lead_row(
                    company=lead.company,
                    contact=lead.contact,
                    lead=lead,
                    score=score,
                    headers=lead_headers,
                )
            )
            if lead.company is not None:
                account_rows.append(
                    self._account_row(
                        company=lead.company,
                        contact=lead.contact,
                        lead=lead,
                        score=score,
                        headers=account_headers,
                    )
                )
            if lead.contact is not None and lead.company is not None:
                contact_rows.append(
                    self._contact_row(
                        company=lead.company,
                        contact=lead.contact,
                        lead=lead,
                        score=score,
                        headers=contact_headers,
                    )
                )
        reply_rows = [self.REPLY_HEADERS]
        activity_rows = [self.ACTIVITY_HEADERS]
        for reply in replies:
            lead_rows_obj = reply.lead
            message = reply.outreach_message
            reply_rows.append(
                self._reply_row(
                    reply=reply,
                    lead=lead_rows_obj,
                    message=message,
                    company=lead_rows_obj.company if lead_rows_obj else None,
                    contact=lead_rows_obj.contact if lead_rows_obj else None,
                )
            )
            activity_rows.append(
                self._activity_row_from_reply(
                    reply=reply,
                    lead=lead_rows_obj,
                    message=message,
                    company=lead_rows_obj.company if lead_rows_obj else None,
                    contact=lead_rows_obj.contact if lead_rows_obj else None,
                )
            )
        delivery_rows = [self.DELIVERY_HEADERS]
        for event in deliveries:
            message = event.outreach_message
            sequence = message.sequence if message else None
            lead = sequence.lead if sequence else None
            delivery_rows.append(
                self._delivery_row(
                    event=event,
                    lead=lead,
                    sequence=sequence,
                    message=message,
                    company=lead.company if lead else None,
                    contact=lead.contact if lead else None,
                )
            )
            activity_rows.append(
                self._activity_row_from_delivery(
                    event=event,
                    lead=lead,
                    sequence=sequence,
                    message=message,
                    company=lead.company if lead else None,
                    contact=lead.contact if lead else None,
                )
            )
        conversion_rows = [self.CONVERSION_HEADERS]
        deal_rows = [deal_headers]
        for event in conversions:
            lead = event.lead
            conversion_rows.append(
                self._conversion_row(
                    event=event,
                    lead=lead,
                    sequence=event.sequence,
                    company=lead.company if lead else None,
                    contact=lead.contact if lead else None,
                )
            )
            deal_rows.append(
                self._deal_row(
                    event=event,
                    lead=lead,
                    sequence=event.sequence,
                    company=lead.company if lead else None,
                    contact=lead.contact if lead else None,
                    headers=deal_headers,
                )
            )
            activity_rows.append(
                self._activity_row_from_conversion(
                    event=event,
                    lead=lead,
                    sequence=event.sequence,
                    company=lead.company if lead else None,
                    contact=lead.contact if lead else None,
                )
            )

        self._replace_table(self.settings.crm_sheet_range_a1, lead_rows)
        self._replace_table(self.settings.crm_sheet_accounts_range_a1, self._dedupe_rows(account_rows))
        self._replace_table(self.settings.crm_sheet_contacts_range_a1, self._dedupe_rows(contact_rows))
        self._replace_table(self.settings.crm_sheet_activities_range_a1, activity_rows)
        self._replace_table(self.settings.crm_sheet_deals_range_a1, self._dedupe_rows(deal_rows))
        self._replace_table(self.settings.crm_sheet_replies_range_a1, reply_rows)
        self._replace_table(self.settings.crm_sheet_delivery_events_range_a1, delivery_rows)
        self._replace_table(self.settings.crm_sheet_conversion_events_range_a1, conversion_rows)
        await self.sync_metrics_snapshot(session=session, metrics_service=metrics_service)
        return {
            "spreadsheet_id": self.settings.crm_sheet_spreadsheet_id,
            "lead_rows": max(len(lead_rows) - 1, 0),
            "account_rows": max(len(self._dedupe_rows(account_rows)) - 1, 0),
            "contact_rows": max(len(self._dedupe_rows(contact_rows)) - 1, 0),
            "activity_rows": max(len(activity_rows) - 1, 0),
            "deal_rows": max(len(self._dedupe_rows(deal_rows)) - 1, 0),
            "reply_rows": max(len(reply_rows) - 1, 0),
            "delivery_rows": max(len(delivery_rows) - 1, 0),
            "conversion_rows": max(len(conversion_rows) - 1, 0),
        }

    async def sync_lead_from_db(self, *, session: AsyncSession, lead_id: str) -> dict[str, Any]:
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
        if lead is None or lead.company is None:
            return {}
        return self.sync_lead_snapshot(
            company=lead.company,
            contact=lead.contact,
            lead=lead,
            score=self._latest_score(lead),
        )

    def _lead_record(
        self,
        *,
        company: Company | None,
        contact: Contact | None,
        lead: Lead,
        score: LeadScore | None,
    ) -> dict[str, Any]:
        source_labels = self._source_labels(company)
        latest_signal = self._latest_signal(company)
        first_name, last_name = self._contact_name_parts(contact)
        if contact is not None:
            latest_signal = self._latest_signal_for_contact(company, contact.id) or latest_signal
        company_meta = dict(company.cloud_signals or {}) if company else {}
        signal_meta = dict(latest_signal.metadata_json or {}) if latest_signal else {}
        priority_score = company_meta.get("priority_score")
        if priority_score in ("", None):
            priority_score = score.total_score if score else ""
        next_action = lead.recommended_sequence or lead.recommended_offer or ""
        return {
            "lead_id": lead.id,
            "created_at": self._iso(lead.created_at),
            "updated_at": self._iso(lead.updated_at or lead.created_at),
            "source": source_labels[0] if source_labels else "",
            "company_id": company.id if company else "",
            "company_name": company.name if company else "",
            "firm": company.name if company else "",
            "company_domain": company.domain if company and company.domain else "",
            "company_website": company.website if company and company.website else "",
            "official_url": company.website if company and company.website else "",
            "company_industry": company.industry if company and company.industry else "",
            "firm_type": company_meta.get("firm_type", company.industry if company else ""),
            "contact_id": contact.id if contact else "",
            "contact_name": contact.full_name if contact and contact.full_name else "",
            "person": contact.full_name if contact and contact.full_name else "",
            "first_name": first_name,
            "last_name": last_name,
            "contact_email": contact.email if contact and contact.email else "",
            "contact_title": contact.title if contact and contact.title else "",
            "country": "",
            "raw_inbound_text": latest_signal.raw_text if latest_signal else "",
            "normalized_summary": latest_signal.extracted_summary if latest_signal and latest_signal.extracted_summary else (lead.recommended_offer or ""),
            "owner": "",
            "fit_score": score.company_fit if score else "",
            "intent_score": score.trigger_strength if score else "",
            "timing_score": score.pain_fit if score else "",
            "priority_score": priority_score,
            "priority_bucket": company_meta.get("priority_bucket", ""),
            "lead_status": lead.status.value,
            "lead_grade": score.lead_grade if score else "",
            "total_score": score.total_score if score else "",
            "recommended_sequence": lead.recommended_sequence or "",
            "recommended_offer": lead.recommended_offer or "",
            "persona_class": lead.persona_class or "",
            "icp_class": lead.icp_class or "",
            "why_now": " | ".join(lead.why_now or []),
            "why_relevant_for_glassbox": company_meta.get("why_relevant_for_glassbox", ""),
            "public_signal": company_meta.get("public_signal", ""),
            "best_entry_route": company_meta.get("best_entry_route", ""),
            "last_verified": company_meta.get("last_verified", ""),
            "stage_fit": signal_meta.get("stage_fit", ""),
            "public_focus": signal_meta.get("public_focus", ""),
            "selected_public_examples": signal_meta.get("selected_public_examples", ""),
            "firm_signal": signal_meta.get("firm_signal", company_meta.get("public_signal", "")),
            "why_fit_for_glassbox": signal_meta.get("why_fit_for_glassbox", ""),
            "suggested_pitch_angle": signal_meta.get("suggested_pitch_angle", ""),
            "intro_path_recommendation": signal_meta.get("intro_path_recommendation", ""),
            "cold_outbound_viability": signal_meta.get("cold_outbound_viability", ""),
            "official_profile_url": signal_meta.get("official_profile_url", ""),
            "crm_status": signal_meta.get("crm_status", ""),
            "next_step": signal_meta.get("next_step", next_action),
            "internal_notes": signal_meta.get("internal_notes", ""),
            "source_labels": " | ".join(source_labels),
            "next_action": next_action,
            "next_action_due": "",
            "last_touch_at": "",
            "last_ai_hash": "",
            "needs_review": 0,
            "validation_errors": "",
            "latest_followup_draft_id": "",
        }

    def _lead_row(
        self,
        *,
        company: Company | None,
        contact: Contact | None,
        lead: Lead,
        score: LeadScore | None,
        headers: list[str] | None = None,
    ) -> list[Any]:
        record = self._lead_record(company=company, contact=contact, lead=lead, score=score)
        return self._row_from_record(record=record, headers=headers or self.LEAD_HEADERS, aliases=self.LEAD_HEADER_ALIASES)

    def _account_record(
        self,
        *,
        company: Company,
        contact: Contact | None,
        lead: Lead,
        score: LeadScore | None,
    ) -> dict[str, Any]:
        latest_signal = self._latest_signal(company)
        source_labels = self._source_labels(company)
        size_band = self._size_band(company.headcount)
        return {
            "account_id": company.id,
            "created_at": self._iso(company.created_at),
            "updated_at": self._iso(company.updated_at),
            "domain": company.domain or "",
            "account_name": company.name,
            "industry": company.industry or "",
            "size_band": size_band,
            "tier": score.lead_grade if score else "",
            "owner": "",
            "account_brief": latest_signal.extracted_summary if latest_signal and latest_signal.extracted_summary else (company.funding_stage or ""),
            "pain_points": " | ".join(lead.why_now or []),
            "proof_points": " | ".join(source_labels),
            "champion": contact.full_name if contact and contact.full_name else "",
            "risk_flags": "",
            "health_score": score.total_score if score else "",
            "last_ai_hash": "",
        }

    def _account_row(
        self,
        *,
        company: Company,
        contact: Contact | None,
        lead: Lead,
        score: LeadScore | None,
        headers: list[str] | None = None,
    ) -> list[Any]:
        record = self._account_record(company=company, contact=contact, lead=lead, score=score)
        return self._row_from_record(record=record, headers=headers or self.ACCOUNT_HEADERS, aliases=self.ACCOUNT_HEADER_ALIASES)

    def _contact_record(
        self,
        *,
        company: Company,
        contact: Contact,
        lead: Lead,
        score: LeadScore | None,
    ) -> dict[str, Any]:
        role_type = contact.inferred_buying_role or contact.function or contact.seniority or ""
        influence = score.persona_fit if score else ""
        return {
            "contact_id": contact.id,
            "created_at": self._iso(contact.created_at),
            "updated_at": self._iso(contact.updated_at),
            "account_id": company.id,
            "name": contact.full_name or full_name(contact.first_name, contact.last_name, None),
            "email": contact.email or "",
            "title": contact.title or "",
            "role_type": role_type,
            "persona": lead.persona_class or "",
            "linkedin_url": contact.linkedin_url or "",
            "influence_score": influence,
        }

    def _contact_row(
        self,
        *,
        company: Company,
        contact: Contact,
        lead: Lead,
        score: LeadScore | None,
        headers: list[str] | None = None,
    ) -> list[Any]:
        record = self._contact_record(company=company, contact=contact, lead=lead, score=score)
        return self._row_from_record(record=record, headers=headers or self.CONTACT_HEADERS, aliases=self.CONTACT_HEADER_ALIASES)

    def _reply_row(
        self,
        *,
        reply: ReplyEvent,
        lead: Lead | None,
        message: OutreachMessage | None,
        company: Company | None,
        contact: Contact | None,
    ) -> list[Any]:
        sequence = message.sequence if message else None
        time_to_reply_hours = ""
        if message and message.sent_at:
            time_to_reply_hours = round(
                max((reply.created_at - message.sent_at).total_seconds() / 3600.0, 0.0),
                2,
            )
        return [
            reply.id,
            self._iso(reply.created_at),
            reply.lead_id,
            sequence.id if sequence else "",
            sequence.sequence_key if sequence else "",
            reply.outreach_message_id or "",
            message.step_number if message else "",
            reply.reply_type.value,
            self._reply_intent(reply),
            reply.sentiment or "",
            lead.status.value if lead else "",
            company.name if company else "",
            contact.full_name if contact else "",
            time_to_reply_hours,
            reply.raw_text,
            self._json(reply.metadata_json),
        ]

    def _delivery_row(
        self,
        *,
        event: DeliveryEvent,
        lead: Lead | None,
        sequence: OutreachSequence | None,
        message: OutreachMessage | None,
        company: Company | None,
        contact: Contact | None,
    ) -> list[Any]:
        return [
            event.id,
            self._iso(event.occurred_at),
            lead.id if lead else event.lead_id or "",
            sequence.id if sequence else "",
            sequence.sequence_key if sequence else "",
            event.outreach_message_id,
            message.step_number if message else "",
            message.channel.value if message else "",
            message.status.value if message else "",
            event.event_type,
            event.provider_event_id or "",
            event.reason or "",
            company.name if company else "",
            contact.full_name if contact else "",
            self._json(event.metadata_json),
        ]

    def _conversion_row(
        self,
        *,
        event: ConversionEvent,
        lead: Lead | None,
        sequence: OutreachSequence | None,
        company: Company | None,
        contact: Contact | None,
    ) -> list[Any]:
        return [
            event.id,
            self._iso(event.occurred_at),
            event.lead_id,
            sequence.id if sequence else event.sequence_id or "",
            sequence.sequence_key if sequence else "",
            event.reply_event_id or "",
            event.event_type,
            event.value if event.value is not None else "",
            event.external_ref or "",
            company.name if company else "",
            contact.full_name if contact else "",
            lead.recommended_offer if lead and lead.recommended_offer else "",
            lead.persona_class if lead and lead.persona_class else "",
            self._json(event.metadata_json),
        ]

    def _deal_record(
        self,
        *,
        event: ConversionEvent,
        lead: Lead | None,
        sequence: OutreachSequence | None,
        company: Company | None,
        contact: Contact | None,
    ) -> dict[str, Any]:
        stage = self._deal_stage(event.event_type)
        probability = 40 if event.event_type == "meeting_booked" else 70
        metadata = event.metadata_json or {}
        return {
            "deal_id": event.external_ref or f"gtm_deal_{event.lead_id}",
            "created_at": self._iso(event.created_at),
            "updated_at": self._iso(event.occurred_at or event.created_at),
            "account_id": company.id if company else "",
            "primary_contact_id": contact.id if contact else "",
            "owner": "",
            "stage": stage,
            "amount": event.value if event.value is not None else "",
            "close_date": metadata.get("close_date", ""),
            "probability": probability,
            "next_step": metadata.get("next_step") or (lead.recommended_offer if lead and lead.recommended_offer else ""),
            "next_step_due": metadata.get("next_step_due", ""),
            "stall_reason": "",
            "risk_flags": "",
            "risk_score": "",
            "health_score": "",
            "last_activity_at": self._iso(event.occurred_at),
            "ai_stage_recommendation": sequence.sequence_key if sequence else (lead.recommended_sequence if lead and lead.recommended_sequence else ""),
            "last_ai_hash": "",
            "needs_review": 0,
            "validation_errors": "",
        }

    def _deal_row(
        self,
        *,
        event: ConversionEvent,
        lead: Lead | None,
        sequence: OutreachSequence | None,
        company: Company | None,
        contact: Contact | None,
        headers: list[str] | None = None,
    ) -> list[Any]:
        record = self._deal_record(event=event, lead=lead, sequence=sequence, company=company, contact=contact)
        return self._row_from_record(record=record, headers=headers or self.DEAL_HEADERS, aliases=self.DEAL_HEADER_ALIASES)

    def _activity_row_from_reply(
        self,
        *,
        reply: ReplyEvent,
        lead: Lead | None,
        message: OutreachMessage | None,
        company: Company | None,
        contact: Contact | None,
    ) -> list[Any]:
        return [
            f"reply_{reply.id}",
            self._iso(reply.created_at),
            "lead",
            lead.id if lead else reply.lead_id,
            message.channel.value if message else "email",
            "inbound",
            self._iso(reply.created_at),
            message.subject if message and message.subject else f"Reply from {contact.full_name if contact and contact.full_name else (company.name if company else 'lead')}",
            self._truncate(reply.raw_text, 500),
            reply.outreach_message_id or "",
            reply.sentiment or "",
            self._reply_intent(reply),
            self._json(reply.metadata_json),
        ]

    def _activity_row_from_delivery(
        self,
        *,
        event: DeliveryEvent,
        lead: Lead | None,
        sequence: OutreachSequence | None,
        message: OutreachMessage | None,
        company: Company | None,
        contact: Contact | None,
    ) -> list[Any]:
        subject = message.subject if message and message.subject else f"Outbound {message.channel.value if message else 'message'}"
        snippet = event.reason or (message.body if message else "")
        return [
            f"delivery_{event.id}",
            self._iso(event.created_at),
            "lead",
            lead.id if lead else event.lead_id or "",
            message.channel.value if message else "email",
            "outbound",
            self._iso(event.occurred_at),
            subject,
            self._truncate(snippet, 500),
            event.provider_event_id or event.outreach_message_id,
            "",
            event.event_type,
            self._json(
                {
                    "company_name": company.name if company else "",
                    "contact_name": contact.full_name if contact and contact.full_name else "",
                    "sequence_id": sequence.id if sequence else "",
                    **(event.metadata_json or {}),
                }
            ),
        ]

    def _activity_row_from_conversion(
        self,
        *,
        event: ConversionEvent,
        lead: Lead | None,
        sequence: OutreachSequence | None,
        company: Company | None,
        contact: Contact | None,
    ) -> list[Any]:
        subject = f"Conversion: {self._deal_stage(event.event_type)}"
        snippet = company.name if company else event.event_type
        return [
            f"conversion_{event.id}",
            self._iso(event.created_at),
            "deal",
            event.external_ref or f"gtm_deal_{event.lead_id}",
            "crm",
            "system",
            self._iso(event.occurred_at),
            subject,
            self._truncate(snippet, 500),
            event.reply_event_id or event.sequence_id or event.lead_id,
            "",
            event.event_type,
            self._json(
                {
                    "lead_id": lead.id if lead else event.lead_id,
                    "sequence_id": sequence.id if sequence else "",
                    "company_name": company.name if company else "",
                    "contact_name": contact.full_name if contact and contact.full_name else "",
                    **(event.metadata_json or {}),
                }
            ),
        ]

    def _upsert_row(self, *, range_a1: str, headers: list[str], key: str, row: list[Any]) -> dict[str, Any]:
        values = self._get_values(range_a1)
        header_present = bool(values and values[0] and values[0][0] == headers[0])
        data_offset = 1 if header_present else 0
        if not values:
            self._write_headers(range_a1, headers)
            response = self._append_values(range_a1, [row])
            return self._write_result(range_a1, response)

        found_row_number = None
        for idx, existing in enumerate(values[data_offset:], start=data_offset + 1):
            if existing and str(existing[0]) == key:
                found_row_number = idx
                break
        if found_row_number is not None:
            row_range = self._row_range(range_a1, found_row_number, len(headers))
            response = self._update_values(row_range, [row])
            result = self._write_result(range_a1, response)
            result["mode"] = "update"
            result["row_number"] = found_row_number
            return result

        if not header_present and values == [[]]:
            self._write_headers(range_a1, headers)
        response = self._append_values(range_a1, [row])
        result = self._write_result(range_a1, response)
        result["mode"] = "append"
        return result

    def _upsert_lead_record(self, *, range_a1: str, record: dict[str, Any]) -> dict[str, Any]:
        return self._upsert_record(
            range_a1=range_a1,
            record=record,
            default_headers=self.LEAD_HEADERS,
            aliases=self.LEAD_HEADER_ALIASES,
            match_priority=self.LEAD_MATCH_PRIORITY,
        )

    def _upsert_record(
        self,
        *,
        range_a1: str,
        record: dict[str, Any],
        default_headers: list[str],
        aliases: dict[str, set[str]],
        match_priority: list[str],
    ) -> dict[str, Any]:
        values = self._get_values(range_a1)
        headers = self._existing_headers(range_a1, values=values) or default_headers
        row = self._row_from_record(record=record, headers=headers, aliases=aliases)
        if not values:
            self._write_headers(range_a1, headers)
            response = self._append_values(range_a1, [row])
            result = self._write_result(range_a1, response)
            result["mode"] = "append"
            return result

        match = self._find_existing_record_row(values=values, headers=headers, record=record, aliases=aliases, match_priority=match_priority)
        if match is not None:
            row_number = match + 1
            row_range = self._row_range(range_a1, row_number, len(headers))
            response = self._update_values(row_range, [row])
            result = self._write_result(range_a1, response)
            result["mode"] = "update"
            result["row_number"] = row_number
            return result

        response = self._append_values(range_a1, [row])
        result = self._write_result(range_a1, response)
        result["mode"] = "append"
        return result

    def _append_activity_row(self, row: list[Any]) -> dict[str, Any]:
        return self._append_row(
            range_a1=self.settings.crm_sheet_activities_range_a1,
            headers=self.ACTIVITY_HEADERS,
            row=row,
        )

    def _append_row(self, *, range_a1: str, headers: list[str], row: list[Any]) -> dict[str, Any]:
        values = self._get_values(range_a1)
        if not values:
            self._write_headers(range_a1, headers)
        response = self._append_values(range_a1, [row])
        result = self._write_result(range_a1, response)
        result["mode"] = "append"
        return result

    def _replace_table(self, range_a1: str, rows: list[list[Any]]) -> dict[str, Any]:
        self._clear_range(range_a1)
        response = self._update_values(self._table_range(range_a1, len(rows[0])), rows)
        return self._write_result(range_a1, response)

    def _write_headers(self, range_a1: str, headers: list[str]) -> None:
        self._update_values(self._header_range(range_a1, len(headers)), [headers])

    def _existing_headers(self, range_a1: str, *, values: list[list[Any]] | None = None) -> list[str] | None:
        rows = values if values is not None else self._get_values(range_a1)
        if not rows:
            return None
        first_row = [str(cell).strip() for cell in rows[0] if str(cell).strip()]
        return first_row or None

    def _merge_headers(self, existing: list[str] | None, defaults: list[str]) -> list[str]:
        if not existing:
            return list(defaults)
        merged = list(existing)
        normalized = {self._normalize_header(header) for header in existing}
        for header in defaults:
            if self._normalize_header(header) not in normalized:
                merged.append(header)
        return merged

    def _find_existing_record_row(
        self,
        *,
        values: list[list[Any]],
        headers: list[str],
        record: dict[str, Any],
        aliases: dict[str, set[str]],
        match_priority: list[str],
    ) -> int | None:
        for canonical_key in match_priority:
            target = str(record.get(canonical_key) or "").strip().lower()
            if not target:
                continue
            index = self._header_index(headers, canonical_key, aliases)
            if index is None:
                continue
            for row_idx, existing in enumerate(values[1:], start=1):
                if index < len(existing) and str(existing[index]).strip().lower() == target:
                    return row_idx
        return None

    def _row_from_record(self, *, record: dict[str, Any], headers: list[str], aliases: dict[str, set[str]]) -> list[Any]:
        row: list[Any] = []
        for header in headers:
            canonical = self._canonical_header(header, aliases)
            if canonical is None:
                row.append("")
                continue
            row.append(record.get(canonical, ""))
        return row

    def _header_index(self, headers: list[str], canonical_key: str, aliases: dict[str, set[str]]) -> int | None:
        for idx, header in enumerate(headers):
            if self._canonical_header(header, aliases) == canonical_key:
                return idx
        return None

    def _canonical_header(self, header: str, aliases: dict[str, set[str]]) -> str | None:
        normalized = self._normalize_header(header)
        for canonical, accepted in aliases.items():
            if normalized in {self._normalize_header(item) for item in accepted}:
                return canonical
        return None

    def _normalize_header(self, value: Any) -> str:
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value).strip()).strip("_")

    def _dedupe_rows(self, rows: list[list[Any]]) -> list[list[Any]]:
        if not rows:
            return rows
        header = rows[0]
        ordered: dict[str, list[Any]] = {}
        for row in rows[1:]:
            key = str(row[0]) if row else ""
            if not key:
                key = json.dumps(row, sort_keys=True, default=str)
            ordered[key] = row
        return [header, *ordered.values()]

    def _get_values(self, range_a1: str) -> list[list[Any]]:
        self._ensure_sheet_exists(range_a1)
        response = self._client().spreadsheets().values().get(
            spreadsheetId=self.settings.crm_sheet_spreadsheet_id,
            range=range_a1,
            majorDimension="ROWS",
        ).execute()
        return response.get("values", [])

    def _append_values(self, range_a1: str, values: list[list[Any]]) -> dict[str, Any]:
        self._ensure_sheet_exists(range_a1)
        return (
            self._client()
            .spreadsheets()
            .values()
            .append(
                spreadsheetId=self.settings.crm_sheet_spreadsheet_id,
                range=range_a1,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )

    def _update_values(self, range_a1: str, values: list[list[Any]]) -> dict[str, Any]:
        self._ensure_sheet_exists(range_a1)
        return (
            self._client()
            .spreadsheets()
            .values()
            .update(
                spreadsheetId=self.settings.crm_sheet_spreadsheet_id,
                range=range_a1,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            )
            .execute()
        )

    def _clear_range(self, range_a1: str) -> dict[str, Any]:
        self._ensure_sheet_exists(range_a1)
        return (
            self._client()
            .spreadsheets()
            .values()
            .clear(
                spreadsheetId=self.settings.crm_sheet_spreadsheet_id,
                range=range_a1,
                body={},
            )
            .execute()
        )

    def _write_result(self, range_a1: str, response: dict[str, Any]) -> dict[str, Any]:
        updates = response.get("updates", response)
        return {
            "spreadsheet_id": self.settings.crm_sheet_spreadsheet_id,
            "sheet_range": range_a1,
            "updated_range": updates.get("updatedRange"),
            "updated_rows": updates.get("updatedRows"),
            "updated_cells": updates.get("updatedCells"),
        }

    def _header_range(self, range_a1: str, width: int) -> str:
        return f"{self._sheet_name(range_a1)}!A1:{self._column_letter(width)}1"

    def _row_range(self, range_a1: str, row_number: int, width: int) -> str:
        return f"{self._sheet_name(range_a1)}!A{row_number}:{self._column_letter(width)}{row_number}"

    def _table_range(self, range_a1: str, width: int) -> str:
        return f"{self._sheet_name(range_a1)}!A1:{self._column_letter(width)}"

    def _sheet_name(self, range_a1: str) -> str:
        sheet_name = range_a1.split("!", 1)[0] if "!" in range_a1 else range_a1
        if len(sheet_name) >= 2 and sheet_name[0] == "'" and sheet_name[-1] == "'":
            return sheet_name[1:-1]
        return sheet_name

    def _column_letter(self, index: int) -> str:
        result = ""
        current = index
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def _source_labels(self, company: Company | None) -> list[str]:
        if company is None:
            return []
        labels: list[str] = []
        for signal in company.signals:
            if signal.source:
                labels.append(signal.source)
            feed_title = (signal.metadata_json or {}).get("feed_title")
            if feed_title:
                labels.append(str(feed_title))
        return list(dict.fromkeys(item.strip() for item in labels if item and item.strip()))[:8]

    def _latest_signal(self, company: Company | None):
        if company is None or not company.signals:
            return None
        return max(
            company.signals,
            key=lambda signal: (
                signal.occurred_at or datetime.min.replace(tzinfo=timezone.utc),
                signal.created_at,
            ),
        )

    def _latest_signal_for_contact(self, company: Company | None, contact_id: str):
        if company is None or not company.signals:
            return None
        scoped = [signal for signal in company.signals if signal.contact_id == contact_id]
        if not scoped:
            return None
        return max(
            scoped,
            key=lambda signal: (
                signal.occurred_at or datetime.min.replace(tzinfo=timezone.utc),
                signal.created_at,
            ),
        )

    def _contact_name_parts(self, contact: Contact | None) -> tuple[str, str]:
        if contact is None:
            return "", ""
        first_name = contact.first_name or ""
        last_name = contact.last_name or ""
        if first_name or last_name:
            return first_name, last_name
        full_name = (contact.full_name or "").strip()
        if not full_name:
            return "", ""
        parts = full_name.split()
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], " ".join(parts[1:])

    def _size_band(self, headcount: int | None) -> str:
        if headcount is None:
            return ""
        if headcount < 11:
            return "1-10"
        if headcount < 51:
            return "11-50"
        if headcount < 201:
            return "51-200"
        if headcount < 501:
            return "201-500"
        return "500+"

    def _deal_stage(self, event_type: str) -> str:
        if event_type == "meeting_booked":
            return "Meeting Booked"
        if event_type == "opportunity_created":
            return "Opportunity Created"
        return event_type.replace("_", " ").title()

    def _truncate(self, value: str | None, limit: int) -> str:
        if not value:
            return ""
        text = str(value)
        if len(text) <= limit:
            return text
        return text[: max(limit - 3, 0)] + "..."

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

    def _latest_score(self, lead: Lead) -> LeadScore | None:
        if not lead.scores:
            return None
        return max(lead.scores, key=lambda item: item.created_at)

    def _iso(self, value: datetime | None) -> str:
        if value is None:
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    def _json(self, value: dict[str, Any] | list[Any] | None) -> str:
        if not value:
            return ""
        return json.dumps(value, sort_keys=True)

    def _scalar(self, value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)
        return value

    def _client(self):
        if self._service is not None:
            return self._service

        try:
            from google.oauth2 import credentials as user_credentials
            from google.oauth2 import service_account
            import google.auth
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('Google extras not installed. Run: pip install ".[google]"') from exc

        creds = None
        if self.settings.google_sheets_service_account_json:
            info = json.loads(self.settings.google_sheets_service_account_json)
            cred_type = str(info.get("type") or "").strip().lower()
            if cred_type == "service_account":
                creds = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=self.settings.sheets_scopes(),
                )
            elif cred_type == "authorized_user":
                creds = user_credentials.Credentials.from_authorized_user_info(
                    info,
                    scopes=self.settings.sheets_scopes(),
                )
            else:
                raise RuntimeError(
                    "Unsupported Google credential type in GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON. "
                    "Expected service_account or authorized_user."
                )
        else:
            creds, _ = google.auth.default(scopes=self.settings.sheets_scopes())

        try:
            self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        except HttpError as exc:  # pragma: no cover
            raise RuntimeError("Failed to initialize Google Sheets client") from exc
        return self._service

    def _ensure_sheet_exists(self, range_a1: str) -> None:
        sheet_name = self._sheet_name(range_a1)
        if not sheet_name:
            return
        titles = self._sheet_titles_cache()
        if sheet_name in titles:
            return
        (
            self._client()
            .spreadsheets()
            .batchUpdate(
                spreadsheetId=self.settings.crm_sheet_spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
            )
            .execute()
        )
        titles.add(sheet_name)

    def _sheet_titles_cache(self) -> set[str]:
        if self._sheet_titles is not None:
            return self._sheet_titles
        response = (
            self._client()
            .spreadsheets()
            .get(
                spreadsheetId=self.settings.crm_sheet_spreadsheet_id,
                fields="sheets(properties(title))",
            )
            .execute()
        )
        self._sheet_titles = {
            str(sheet.get("properties", {}).get("title") or "").strip()
            for sheet in response.get("sheets", [])
            if str(sheet.get("properties", {}).get("title") or "").strip()
        }
        return self._sheet_titles
