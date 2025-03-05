import base64
import hashlib
import hmac
import json
import os
import threading
import time
from datetime import timedelta

import requests
from agora_token_builder import RtcTokenBuilder
from django.conf import settings
from django.utils import timezone
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except Exception:
    firebase_admin = None
    credentials = None
    messaging = None

from .models import CallSession


def generate_agora_uids(call_session):
    base = int(call_session.subscription_id or 1) * 1000
    caller_uid = base + int(call_session.caller_id)
    callee_uid = base + int(call_session.callee_id) + 500000
    return caller_uid, callee_uid


def build_channel_name(caller_id, callee_id):
    return f"buzzy-call-{caller_id}-{callee_id}-{int(time.time())}"


def generate_agora_token_payload(channel_name, uid, allowed_seconds, call_id):
    now_ts = int(time.time())
    expire_ts = now_ts + max(1, int(allowed_seconds))
    app_id = getattr(settings, "AGORA_APP_ID", "")
    app_cert = getattr(settings, "AGORA_APP_CERTIFICATE", "")

    if app_id and app_cert:
        # Role_Publisher = 1
        token = RtcTokenBuilder.buildTokenWithUid(
            app_id, app_cert, channel_name, uid, 1, expire_ts
        )
        provider = "agora_v2"
    else:
        raw = json.dumps({
            "channel_name": channel_name,
            "uid": uid,
            "expire_ts": expire_ts,
            "call_id": str(call_id),
        }).encode()
        token = base64.urlsafe_b64encode(raw).decode()
        provider = "mock"

    return {
        "token": token,
        "expire_ts": expire_ts,
        "provider": provider,
        "app_id": app_id,
    }


def send_call_push_notification(receiver, payload):
    """
    Envía una notificación de llamada entrante usando Firebase Admin SDK (HTTP v1).
    """
    # 1. Obtención limpia del token desde el modelo OnlineStatus
    online_status = getattr(receiver, "online_status", None)
    device_token = online_status.device_token if online_status else None

    if not device_token:
        return {"sent": False, "reason": "missing_device_token"}

    # 2. Construcción del mensaje profesional
    try:
        # Extraemos el nombre para el cuerpo del mensaje
        caller_name = payload.get('caller_username', 'Alguien')
        
        # 2. Construcción del mensaje profesional
        data_payload = {k: str(v) for k, v in payload.items()}
        data_payload['type'] = 'incoming_call'  # Identificador para el frontend
        
        message = messaging.Message(
            token=device_token,
            data=data_payload,
            # 'notification' es lo que el usuario ve en el banner del celular
            notification=messaging.Notification(
                title="📞 Llamada entrante",
                body=f"{caller_name} te está llamando",
            ),
            # Prioridad alta para que la notificación llegue incluso con batería baja
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    click_action="OPEN_CALL_SCREEN" # Opcional: para manejar clicks
                )
            ),
            # Configuración para dispositivos Apple (si los usas en el futuro)
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(content_available=True)
                )
            ),
        )
        # 3. Envío a través del SDK oficial
        response = messaging.send(message)
        
        return {
            "sent": True, 
            "message_id": response, 
            "provider": "firebase_v1"
        }

    except Exception as exc:
        return {
            "sent": False, 
            "provider": "firebase_v1", 
            "reason": str(exc)
        }

def agora_force_close_channel(call_session):
    customer_id = getattr(settings, "AGORA_CUSTOMER_ID", "")
    customer_secret = getattr(settings, "AGORA_CUSTOMER_SECRET", "")
    app_id = getattr(settings, "AGORA_APP_ID", "")

    if not (customer_id and customer_secret and app_id):
        return {"sent": False, "reason": "missing_agora_rest_credentials"}

    auth = base64.b64encode(f"{customer_id}:{customer_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }
    payload = {
        "cname": call_session.channel_name,
        "uid": str(call_session.agora_uid_caller),
    }

    # Best-effort placeholder endpoint shape; can be swapped to the exact Agora rule-based API in prod.
    endpoint = f"https://api.agora.io/dev/v1/kicking-rule/{app_id}/rules"
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=5)
        return {"sent": response.ok, "status_code": response.status_code, "body": response.text[:300]}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)}


def finalize_call_session(call_session, reason="ended", consumed_seconds=None, force_close=False):
    if call_session.status in {"ended", "expired", "failed", "missed", "rejected"}:
        return call_session

    now = timezone.now()
    if consumed_seconds is None:
        if call_session.answered_at:
            consumed_seconds = max(0, int((now - call_session.answered_at).total_seconds()))
        else:
            consumed_seconds = 0  # No cobrar si nunca se contestó

    capped_seconds = min(consumed_seconds, call_session.allowed_seconds or consumed_seconds)
    call_session.consumed_seconds = capped_seconds
    call_session.ended_at = now
    call_session.ended_reason = reason
    call_session.status = "expired" if reason == "expired" else "ended"
    call_session.save(update_fields=["consumed_seconds", "ended_at", "ended_reason", "status"])

    call_session.subscription.consume_call_seconds(capped_seconds, call_session.call_type)

    if force_close:
        rest_result = agora_force_close_channel(call_session)
        metadata = call_session.metadata or {}
        metadata["agora_force_close"] = rest_result
        call_session.metadata = metadata
        call_session.save(update_fields=["metadata"])

    return call_session


def schedule_call_kill(call_session):
    delay = max(1, int(call_session.allowed_seconds))

    def _expire():
        try:
            fresh = CallSession.objects.select_related("subscription").get(pk=call_session.pk)
            if fresh.status in {"ended", "expired", "failed", "missed", "rejected"}:
                return
            finalize_call_session(fresh, reason="expired", consumed_seconds=fresh.allowed_seconds, force_close=True)
        except Exception as exc:
            try:
                fresh = CallSession.objects.get(pk=call_session.pk)
                metadata = fresh.metadata or {}
                metadata["kill_switch_error"] = str(exc)
                fresh.metadata = metadata
                fresh.save(update_fields=["metadata"])
            except Exception:
                pass

    timer = threading.Timer(delay, _expire)
    timer.daemon = True
    timer.start()
    return timer


def get_call_payload(call_session, caller_token, callee_token):
    base = {
        "uuid": str(call_session.uuid),
        "channel_name": call_session.channel_name,
        "call_type": call_session.call_type,
        "allowed_seconds": call_session.allowed_seconds,
        "expires_at": call_session.agora_token_expire_at.isoformat() if call_session.agora_token_expire_at else None,
        "agora_uid_caller": call_session.agora_uid_caller,
        "agora_uid_callee": call_session.agora_uid_callee,
        "caller": {
            "id": call_session.caller_id,
            "username": call_session.caller.username,
        },
        "callee": {
            "id": call_session.callee_id,
            "username": call_session.callee.username,
        },
    }
    return {
        "caller": {
            **base,
            "agora_uid": call_session.agora_uid_caller,
            "token": caller_token["token"],
            "token_provider": caller_token["provider"],
            "app_id": caller_token["app_id"],
        },
        "callee": {
            **base,
            "agora_uid": call_session.agora_uid_callee,
            "token": callee_token["token"],
            "token_provider": callee_token["provider"],
            "app_id": callee_token["app_id"],
        },
    }
