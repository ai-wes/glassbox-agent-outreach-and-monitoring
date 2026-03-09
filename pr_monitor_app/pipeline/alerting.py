from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.config import settings
from pr_monitor_app.email.sender import build_email_sender
from pr_monitor_app.models import Alert, AlertTier, Client, ClientEvent, Event, EventCluster, EventClusterMap, NotificationChannel, StrategicBrief, TopicLens
from pr_monitor_app.signal.sender import build_signal_sender
from pr_monitor_app.state import StateStore
from pr_monitor_app.telegram.sender import build_telegram_sender
from pr_monitor_app.utils.text import normalize_text
from pr_monitor_app.whatsapp.sender import build_whatsapp_sender

log = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hour_bucket(dt: datetime) -> str:
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y%m%d%H")


def _tier_emoji(t: AlertTier) -> str:
    return {"P0": "🛑", "P1": "🚨", "P2": "🟡", "P3": "🗄️"}.get(t.value, "🔔")


def _format_message(
    *,
    tier: AlertTier,
    client: Client,
    topic: TopicLens,
    event: Event,
    brief: Optional[StrategicBrief],
) -> str:
    headline = event.title or (event.raw_text[:120] if event.raw_text else "Update")
    why = ""
    engage = ""
    link = ""

    if brief:
        sa = brief.strategic_analysis or {}
        why = normalize_text(sa.get("why_it_matters") or "")
        engage_mode = str(sa.get("engagement_mode_recommendation") or brief.engagement_mode.value)
        engage = _engagement_bullets(engage_mode, brief)
        link = f"{settings.dashboard_base_url.rstrip('/')}/briefs/{brief.id}"
    else:
        why = normalize_text((event.raw_text or "")[:220])
        engage = "→ Review and decide engagement mode."
        link = event.url

    lines = [
        f"{_tier_emoji(tier)} {tier.value} | Client: {client.name} | Topic: {topic.name}",
        "",
        "Headline:",
        headline.strip(),
        "",
        "Why it matters:",
        why.strip()[:450],
        "",
        "Engagement recommendation:",
        engage.strip(),
        "",
        f"Open brief: {link}",
    ]
    return "\n".join(lines).strip()


def _engagement_bullets(mode: str, brief: StrategicBrief) -> str:
    m = (mode or "").lower()
    if m == "comment":
        return "→ Comment on the original post/article\n→ Keep it grounded; add one actionable insight\n→ Avoid unverified claims"
    if m == "independent_post":
        return "→ Publish a perspective post within 12–24 hrs\n→ Use a clear framework; invite discussion\n→ Keep claims tightly sourced"
    if m == "thread":
        return "→ Write a short thread (3–6 bullets)\n→ Lead with the nuance most miss\n→ End with a question to drive replies"
    if m == "journalist_outreach":
        return "→ Consider proactive outreach (if you have a relationship)\n→ Offer a non-promotional expert angle\n→ Avoid speculation and hard predictions"
    if m == "stay_silent":
        return "→ Recommend staying silent for now\n→ Monitor the narrative and competitor moves\n→ Re-engage if new facts emerge"
    return "→ Review and decide engagement mode."


class _Sender(Protocol):
    async def send(self, **kwargs: Any) -> Any:
        ...


def _resolve_destinations(client: Client) -> list[tuple[NotificationChannel, str]]:
    out: list[tuple[NotificationChannel, str]] = []

    signal_recipient = (client.signal_recipient or settings.signal_recipient_default or "").strip()
    if signal_recipient:
        out.append((NotificationChannel.signal, signal_recipient))

    telegram_recipient = (client.telegram_recipient or settings.telegram_recipient_default or "").strip()
    if telegram_recipient:
        out.append((NotificationChannel.telegram, telegram_recipient))

    whatsapp_recipient = (client.whatsapp_recipient or settings.whatsapp_recipient_default or "").strip()
    if whatsapp_recipient:
        out.append((NotificationChannel.whatsapp, whatsapp_recipient))

    email_recipient = (client.email_recipient or settings.email_recipient_default or "").strip()
    if email_recipient:
        out.append((NotificationChannel.email, email_recipient))

    return out


def _sender_for_channel(channel: NotificationChannel, cache: dict[NotificationChannel, _Sender]) -> _Sender:
    sender = cache.get(channel)
    if sender is not None:
        return sender

    if channel == NotificationChannel.signal:
        sender = build_signal_sender()
    elif channel == NotificationChannel.telegram:
        sender = build_telegram_sender()
    elif channel == NotificationChannel.whatsapp:
        sender = build_whatsapp_sender()
    elif channel == NotificationChannel.email:
        sender = build_email_sender()
    else:
        raise ValueError(f"Unsupported notification channel: {channel}")

    cache[channel] = sender
    return sender


async def send_alerts(session: AsyncSession, *, limit: int = 200) -> dict[str, Any]:
    """
    Create + send alerts (Signal / Telegram / WhatsApp) for ClientEvents (P0–P2) that:
      - are representative of their cluster (dedupe)
      - are not already alerted
      - pass rate limit
    """
    state = StateStore.from_settings()
    sender_cache: dict[NotificationChannel, _Sender] = {}

    # Find candidate client events with no alerts yet
    alerted_subq = select(Alert.client_event_id).subquery()

    rows = (
        await session.execute(
            select(ClientEvent, Client, TopicLens, Event)
            .join(Client, Client.id == ClientEvent.client_id)
            .join(TopicLens, TopicLens.id == ClientEvent.topic_id)
            .join(Event, Event.id == ClientEvent.event_id)
            .where(
                ClientEvent.tier.in_([AlertTier.P0, AlertTier.P1, AlertTier.P2]),
                ~ClientEvent.id.in_(select(alerted_subq.c.client_event_id)),
            )
            .order_by(ClientEvent.created_at.asc())
            .limit(limit)
        )
    ).all()

    sent = 0
    skipped = 0
    created = 0

    for ce, client, topic, event in rows:
        try:
            # Cluster dedupe: only alert on representative event
            rep_ok = await _is_cluster_representative(session, event.id)
            if not rep_ok:
                skipped += 1
                continue

            # Redis dedupe window per client+cluster
            cluster_id = await _cluster_id(session, event.id)
            if cluster_id:
                dedup_key = f"npe:dedup:client:{client.id}:cluster:{cluster_id}"
                added = state.sadd(dedup_key, "1", ttl_seconds=settings.alert_dedup_window_minutes * 60)
                if added == 0:
                    skipped += 1
                    continue

            # Rate limit per client per hour
            hour_key = f"npe:rate:client:{client.id}:{_hour_bucket(_now())}"
            count = state.incr_with_ttl(hour_key, ttl_seconds=3600)
            if count > settings.alert_max_per_client_per_hour:
                skipped += 1
                continue

            brief = await _get_brief(session, ce.id)

            msg = _format_message(tier=ce.tier, client=client, topic=topic, event=event, brief=brief)
            destinations = _resolve_destinations(client)
            if not destinations:
                raise ValueError(
                    f"No alert recipients configured for client={client.name}. "
                    "Set client recipients or *_RECIPIENT_DEFAULT env vars."
                )

            for channel, recipient in destinations:
                alert = Alert(
                    client_event_id=ce.id,
                    tier=ce.tier,
                    message_text=msg,
                    channel=channel,
                    recipient=recipient,
                    # Legacy field kept for backward compatibility with existing schema.
                    signal_recipient=recipient,
                    status="pending",
                )
                session.add(alert)
                await session.flush()
                created += 1

                try:
                    sender = _sender_for_channel(channel, sender_cache)
                    if channel == NotificationChannel.email:
                        subject = f"[{ce.tier.value}] {client.name} — {topic.name}"
                        res = await sender.send(recipient=recipient, subject=subject, body_text=msg)
                    else:
                        res = await sender.send(recipient=recipient, message=msg)
                    alert.status = "sent" if getattr(res, "ok", False) else "failed"
                    alert.sent_at = _now() if alert.status == "sent" else None
                    sent += 1 if alert.status == "sent" else 0
                except Exception as send_error:
                    alert.status = "failed"
                    alert.sent_at = None
                    skipped += 1
                    log.exception(
                        "send_alert_channel_failed",
                        client_event_id=str(ce.id),
                        channel=channel.value,
                        recipient=recipient,
                        error=str(send_error),
                    )

        except Exception as e:
            skipped += 1
            log.exception("send_alert_failed", client_event_id=str(ce.id), error=str(e))

    log.info("alerts_done", created=created, sent=sent, skipped=skipped)
    return {"created": created, "sent": sent, "skipped": skipped}


async def _get_brief(session: AsyncSession, client_event_id) -> Optional[StrategicBrief]:
    return (await session.execute(select(StrategicBrief).where(StrategicBrief.client_event_id == client_event_id))).scalar_one_or_none()


async def _cluster_id(session: AsyncSession, event_id) -> Optional[str]:
    row = (await session.execute(select(EventClusterMap.cluster_id).where(EventClusterMap.event_id == event_id))).scalar_one_or_none()
    return str(row) if row else None


async def _is_cluster_representative(session: AsyncSession, event_id) -> bool:
    row = (
        await session.execute(
            select(EventCluster.representative_event_id)
            .join(EventClusterMap, EventClusterMap.cluster_id == EventCluster.id)
            .where(EventClusterMap.event_id == event_id)
        )
    ).scalar_one_or_none()

    if row is None:
        # event not clustered yet => treat as representative to avoid drop
        return True
    return str(row) == str(event_id)
