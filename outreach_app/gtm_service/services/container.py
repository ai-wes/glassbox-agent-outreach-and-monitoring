from __future__ import annotations

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.services.crm import SheetsCRMService
from outreach_app.gtm_service.services.lead_sources import SourceIngestionService
from outreach_app.gtm_service.services.llm import LLMClient
from outreach_app.gtm_service.services.mailer import EmailDeliveryService, LinkedInDispatchService
from outreach_app.gtm_service.services.metrics import MetricsService
from outreach_app.gtm_service.services.outreach import OutreachGenerator
from outreach_app.gtm_service.services.research import ResearchAgent
from outreach_app.gtm_service.services.router import LeadRouter
from outreach_app.gtm_service.services.scoring import LeadScoringService
from outreach_app.gtm_service.services.sequencer import SequenceService


class ServiceContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm_client = LLMClient(settings) if settings.llm_ready else None
        self.source_service = SourceIngestionService(settings)
        self.research_agent = ResearchAgent(settings, self.llm_client)
        self.scoring_service = LeadScoringService(settings, self.llm_client)
        self.router = LeadRouter()
        self.outreach_generator = OutreachGenerator(settings)
        self.mailer = EmailDeliveryService(settings)
        self.linkedin_dispatch = LinkedInDispatchService(settings)
        self.crm_sync_service = SheetsCRMService(settings)
        self.sequence_service = SequenceService(
            settings,
            self.mailer,
            self.linkedin_dispatch,
            self.outreach_generator,
            self.crm_sync_service,
        )
        self.metrics_service = MetricsService()

    async def aclose(self) -> None:
        await self.source_service.close()
        await self.linkedin_dispatch.close()
        await self.crm_sync_service.close()
        if self.llm_client is not None:
            await self.llm_client.close()
