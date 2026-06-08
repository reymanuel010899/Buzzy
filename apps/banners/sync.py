from django.utils import timezone
from django.db.models import Count


def _get_user_field_value(user, field):
    """Evalúa el valor de un campo del usuario para comparar con el requisito."""
    from apps.subscriptions.models import UserSubscription
    from apps.videos.models import Video

    if field == 'has_subscription':
        return UserSubscription.objects.filter(subscriber=user, is_active=True).exists()

    if field == 'subscription_plan':
        sub = UserSubscription.objects.filter(subscriber=user, is_active=True).select_related('plan').first()
        return sub.plan.name if sub and sub.plan else ''

    if field == 'followers_count':
        return user.followers.count()

    if field == 'following_count':
        return user.following.count()

    if field == 'account_age_days':
        if hasattr(user, 'date_joined') and user.date_joined:
            return (timezone.now() - user.date_joined).days
        return 0

    if field == 'total_videos':
        return Video.objects.filter(user_id=user).count()

    if field == 'is_buzzy_premium':
        return getattr(user, 'is_buzzy_premium', False)

    if field == 'country':
        return user.country.code if user.country else ''

    if field == 'total_tokens':
        try:
            return float(user.wallet.balance)
        except Exception:
            return 0

    if field == 'videos_this_month':
        now = timezone.now()
        return Video.objects.filter(
            user_id=user,
            created_at__year=now.year,
            created_at__month=now.month
        ).count()

    return None


def _evaluate_requirement(user, requirement):
    """Retorna True si el usuario cumple el requisito."""
    value = _get_user_field_value(user, requirement.field)
    op = requirement.operator
    req_value = requirement.value.strip()

    # Booleans
    if isinstance(value, bool):
        return value == (req_value.lower() in ('true', '1', 'yes'))

    # Lista
    if op == 'in':
        options = [v.strip() for v in req_value.split(',')]
        return str(value) in options

    # Numéricos
    try:
        value = float(value)
        req_value = float(req_value)
    except (TypeError, ValueError):
        # String comparison
        if op == 'eq':
            return str(value).lower() == str(req_value).lower()
        return False

    if op == 'eq':
        return value == req_value
    if op == 'gt':
        return value > req_value
    if op == 'lt':
        return value < req_value
    if op == 'gte':
        return value >= req_value
    if op == 'lte':
        return value <= req_value

    return False


def _user_meets_group(user, group):
    """Retorna True si el usuario cumple TODOS los requisitos del grupo (AND)."""
    requirements = group.requirements.all()
    if not requirements.exists():
        return False
    return all(_evaluate_requirement(user, req) for req in requirements)


def sync_all_groups(group_id=None):
    """
    Sincroniza membresías automáticas.
    - Agrega usuarios que cumplen requisitos
    - Remueve usuarios AUTO que ya no los cumplen
    - Nunca toca membresías MANUAL
    Retorna (added, removed).
    """
    from apps.users.models import User
    from .models import UserGroup, UserGroupMembership

    added = 0
    removed = 0

    groups = UserGroup.objects.filter(is_auto=True)
    if group_id:
        groups = groups.filter(pk=group_id)

    users = User.objects.filter(is_active=True).select_related('country')

    for group in groups:
        for user in users:
            meets = _user_meets_group(user, group)
            membership = UserGroupMembership.objects.filter(user=user, group=group).first()

            if meets and not membership:
                UserGroupMembership.objects.create(user=user, group=group, added_by='AUTO')
                added += 1
            elif not meets and membership and membership.added_by == 'AUTO':
                membership.delete()
                removed += 1

    return added, removed
