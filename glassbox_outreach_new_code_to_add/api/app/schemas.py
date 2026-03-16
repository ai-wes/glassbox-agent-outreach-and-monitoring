"""Pydantic models for API requests and responses.

These schemas define the structure of data exchanged between clients
and the API.  They are separate from the SQLAlchemy models to avoid
coupling database concerns directly to the API layer.  Each schema
uses ``model_config = ConfigDict(from_attributes=True)`` to allow
conversion from ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict


class CompanyBase(BaseModel):
    name: str
    domain: Optional[str] = None
    website: Optional[str] = None
    headcount: Optional[int] = None
    funding_stage: Optional[str] = None
    industry: Optional[str] = None
    ai_bio_relevance: Optional[float] = None


class CompanyCreate(CompanyBase):
    pass


class CompanyRead(CompanyBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContactBase(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[EmailStr] = None
    seniority: Optional[str] = None
    function: Optional[str] = None
    inferred_buying_role: Optional[str] = None
    email_verified: bool = False


class ContactCreate(ContactBase):
    pass


class ContactRead(ContactBase):
    id: str
    company_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadBase(BaseModel):
    company_id: str
    contact_id: Optional[str] = None
    status: str
    fit_score: Optional[float] = None
    email_confidence: Optional[float] = None
    icp_class: Optional[str] = None
    persona_class: Optional[str] = None
    recommended_sequence: Optional[str] = None
    recommended_offer: Optional[str] = None
    why_now: Optional[str] = None


class LeadCreate(BaseModel):
    company: CompanyCreate
    contact: Optional[ContactCreate] = None


class LeadRead(LeadBase):
    id: str
    created_at: datetime
    updated_at: datetime
    last_scored_at: Optional[datetime] = None
    company: CompanyRead
    contact: Optional[ContactRead] = None

    model_config = ConfigDict(from_attributes=True)


class JobCreate(BaseModel):
    job_type: str = Field(..., description="Type of job to create, e.g. discovery")
    urls: List[str] = Field(..., description="List of URLs to process in the job")


class JobRead(BaseModel):
    id: str
    job_type: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    row_count: Optional[int] = None
    success_count: Optional[int] = None
    failure_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class SheetsReadRequest(BaseModel):
    spreadsheet_id: Optional[str] = None
    range_a1: str


class SheetsAppendRequest(BaseModel):
    spreadsheet_id: Optional[str] = None
    range_a1: str
    values: List[List[str]]
    value_input_option: str = "USER_ENTERED"
    insert_data_option: str = "INSERT_ROWS"


class SheetsUpdateRequest(BaseModel):
    spreadsheet_id: Optional[str] = None
    range_a1: str
    values: List[List[str]]


class SheetsClearRequest(BaseModel):
    spreadsheet_id: Optional[str] = None
    range_a1: str