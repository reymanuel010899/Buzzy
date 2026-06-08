import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from celery import shared_task

logger = logging.getLogger(__name__)


def _get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _refresh_facebook(account, session):
    pages_resp = session.get(
        "https://graph.facebook.com/v19.0/me/accounts",
        params={"access_token": account.access_token, "fields": "id,name,fan_count,access_token"},
        timeout=15,
    )
    pages = pages_resp.json().get("data", [])
    if pages:
        page = pages[0]
        page_access_token = page.get("access_token", account.access_token)
        fan_count = page.get("fan_count", 0)
        if fan_count == 0:
            page_resp = session.get(
                f"https://graph.facebook.com/v19.0/{page['id']}",
                params={"fields": "fan_count,followers_count", "access_token": page_access_token},
                timeout=15,
            )
            page_data = page_resp.json()
            fan_count = page_data.get("fan_count") or page_data.get("followers_count", 0)
        return fan_count
    return None  # No pages found — skip update


def _refresh_instagram(account, session):
    resp = session.get(
        "https://graph.instagram.com/me",
        params={"fields": "followers_count", "access_token": account.access_token},
        timeout=15,
    )
    data = resp.json()
    return data.get("followers_count")


def _refresh_tiktok(account, session):
    resp = session.get(
        "https://open.tiktokapis.com/v2/user/info/",
        headers={"Authorization": f"Bearer {account.access_token}"},
        params={"fields": "open_id,display_name,follower_count"},
        timeout=15,
    )
    data = resp.json()
    return data.get("data", {}).get("user", {}).get("follower_count")


@shared_task(name="apps.users.tasks.refresh_all_social_followers", bind=True, max_retries=0)
def refresh_all_social_followers(self):
    from .models import SocialAccount

    accounts = SocialAccount.objects.select_related("user").all()
    session = _get_session()
    updated = 0
    failed = 0

    refreshers = {
        "facebook": _refresh_facebook,
        "instagram": _refresh_instagram,
        "tiktok": _refresh_tiktok,
    }

    for account in accounts:
        refresher = refreshers.get(account.platform)
        if not refresher:
            continue
        try:
            count = refresher(account, session)
            if count is not None and count != account.followers_count:
                account.followers_count = count
                account.save(update_fields=["followers_count"])
                updated += 1
        except Exception as exc:
            logger.warning("Failed to refresh %s for user %s: %s", account.platform, account.user_id, exc)
            failed += 1

    logger.info("refresh_all_social_followers: %d updated, %d failed", updated, failed)
    return {"updated": updated, "failed": failed}
