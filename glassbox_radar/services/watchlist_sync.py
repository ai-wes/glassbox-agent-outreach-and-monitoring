from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from glassbox_radar.models import Company, Contact, Program
from glassbox_radar.watchlist import WatchlistCompany


async def sync_watchlist(session: AsyncSession, companies: list[WatchlistCompany]) -> dict[str, int]:
    synced_companies = 0
    synced_programs = 0
    synced_contacts = 0

    for company_payload in companies:
        company_result = await session.execute(select(Company).where(Company.name == company_payload.name))
        company = company_result.scalar_one_or_none()
        if company is None:
            company = Company(name=company_payload.name)
            session.add(company)

        company.domain = company_payload.domain
        company.aliases = company_payload.aliases
        company.hq = company_payload.hq
        company.stage = company_payload.stage
        company.last_raise_date = company_payload.last_raise_date
        company.last_raise_amount = company_payload.last_raise_amount
        company.runway_months = company_payload.runway_months
        company.lead_investors = company_payload.lead_investors
        company.board_members = company_payload.board_members
        company.therapeutic_areas = company_payload.therapeutic_areas
        company.warm_intro_paths = company_payload.warm_intro_paths
        company.rss_feeds = company_payload.rss_feeds
        company.is_active = True
        synced_companies += 1

        await session.flush()

        existing_programs_result = await session.execute(select(Program).where(Program.company_id == company.id))
        existing_programs = existing_programs_result.scalars().all()
        existing_program_index = {
            (program.asset_name or "", program.target or ""): program for program in existing_programs
        }

        for program_payload in company_payload.programs:
            key = (program_payload.asset_name or "", program_payload.target or "")
            program = existing_program_index.get(key)
            if program is None:
                program = Program(company_id=company.id)
                session.add(program)

            program.asset_name = program_payload.asset_name
            program.target = program_payload.target
            program.mechanism = program_payload.mechanism
            program.modality = program_payload.modality
            program.indication = program_payload.indication
            program.stage = program_payload.stage
            program.key_terms = program_payload.key_terms
            program.lead_program_flag = program_payload.lead_program_flag
            synced_programs += 1

        existing_contacts_result = await session.execute(select(Contact).where(Contact.company_id == company.id))
        existing_contacts = existing_contacts_result.scalars().all()
        existing_contact_index = {contact.email or contact.name: contact for contact in existing_contacts}

        for contact_payload in company_payload.contacts:
            key = contact_payload.email or contact_payload.name
            contact = existing_contact_index.get(key)
            if contact is None:
                contact = Contact(company_id=company.id, name=contact_payload.name)
                session.add(contact)

            contact.name = contact_payload.name
            contact.title = contact_payload.title
            contact.email = contact_payload.email
            contact.phone = contact_payload.phone
            contact.linkedin_url = contact_payload.linkedin_url
            contact.role = contact_payload.role
            contact.warm_intro_strength = contact_payload.warm_intro_strength
            contact.is_primary = contact_payload.is_primary
            synced_contacts += 1

    await session.commit()
    return {
        "companies": synced_companies,
        "programs": synced_programs,
        "contacts": synced_contacts,
    }
