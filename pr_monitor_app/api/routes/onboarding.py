from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.onboarding_schemas import (
    BlueprintReviewDecisionIn,
    ConfirmCandidateIn,
    MaterializeBlueprintIn,
    MaterializationResultOut,
    MonitoringBlueprintProposalOut,
    OnboardingAutoOut,
    OnboardingIntakeIn,
    OnboardingSessionDetailOut,
    OnboardingSessionOut,
)
from pr_monitor_app.onboarding_service import (
    auto_onboard,
    confirm_resolution_candidate,
    create_onboarding_session,
    enrich_onboarding_session,
    generate_onboarding_blueprint,
    get_blueprint_for_session,
    get_onboarding_session_detail,
    list_onboarding_sessions,
    materialize_onboarding_session,
    resolve_onboarding_session,
    review_onboarding_blueprint,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/sessions", response_model=OnboardingSessionDetailOut, status_code=201)
async def create_session(
    payload: OnboardingIntakeIn,
    session: AsyncSession = Depends(get_session),
) -> OnboardingSessionDetailOut:
    return await create_onboarding_session(session, payload)


@router.get("/sessions", response_model=list[OnboardingSessionOut])
async def get_sessions(
    limit: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[OnboardingSessionOut]:
    return await list_onboarding_sessions(session, limit=limit)


@router.get("/sessions/{session_id}", response_model=OnboardingSessionDetailOut)
async def get_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> OnboardingSessionDetailOut:
    try:
        return await get_onboarding_session_detail(session, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/sessions/{session_id}/resolve", response_model=OnboardingSessionDetailOut)
async def resolve_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> OnboardingSessionDetailOut:
    try:
        return await resolve_onboarding_session(session, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/sessions/{session_id}/confirm-candidate", response_model=OnboardingSessionDetailOut)
async def confirm_candidate(
    session_id: uuid.UUID,
    payload: ConfirmCandidateIn,
    session: AsyncSession = Depends(get_session),
) -> OnboardingSessionDetailOut:
    try:
        return await confirm_resolution_candidate(session, session_id, payload)
    except ValueError as exc:
        raise _bad_request(exc)


@router.post("/sessions/{session_id}/enrich", response_model=OnboardingSessionDetailOut)
async def enrich_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> OnboardingSessionDetailOut:
    try:
        return await enrich_onboarding_session(session, session_id)
    except ValueError as exc:
        raise _bad_request(exc)


@router.post("/sessions/{session_id}/generate-blueprint", response_model=OnboardingSessionDetailOut)
async def generate_blueprint(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> OnboardingSessionDetailOut:
    try:
        return await generate_onboarding_blueprint(session, session_id)
    except ValueError as exc:
        raise _bad_request(exc)


@router.get("/sessions/{session_id}/blueprint", response_model=MonitoringBlueprintProposalOut)
async def get_blueprint(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> MonitoringBlueprintProposalOut:
    try:
        return await get_blueprint_for_session(session, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/sessions/{session_id}/review", response_model=OnboardingSessionDetailOut)
async def review_blueprint(
    session_id: uuid.UUID,
    payload: BlueprintReviewDecisionIn,
    session: AsyncSession = Depends(get_session),
) -> OnboardingSessionDetailOut:
    try:
        return await review_onboarding_blueprint(session, session_id, payload)
    except ValueError as exc:
        raise _bad_request(exc)


@router.post("/sessions/{session_id}/materialize", response_model=MaterializationResultOut)
async def materialize_blueprint(
    session_id: uuid.UUID,
    payload: MaterializeBlueprintIn,
    session: AsyncSession = Depends(get_session),
) -> MaterializationResultOut:
    try:
        return await materialize_onboarding_session(session, session_id, payload)
    except ValueError as exc:
        raise _bad_request(exc)


@router.post("/auto", response_model=OnboardingAutoOut)
async def auto_session(
    payload: OnboardingIntakeIn,
    session: AsyncSession = Depends(get_session),
) -> OnboardingAutoOut:
    return await auto_onboard(session, payload)
