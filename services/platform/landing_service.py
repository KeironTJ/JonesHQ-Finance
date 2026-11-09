from urllib.parse import unquote, urlsplit

from flask import url_for


class LandingService:
    WORKSPACES = {
        'central': ('Central Hub', 'central.hub'),
        'finance': ('Finance', 'dashboard.index'),
    }

    @staticmethod
    def workspace_for(user):
        return (user.preferences or {}).get('default_workspace', 'central')

    @staticmethod
    def safe_next(target):
        if not isinstance(target, str):
            return None
        decoded = unquote(target)
        if (
            not decoded.startswith('/') or decoded.startswith('//')
            or '\\' in decoded or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
        ):
            return None
        try:
            parsed = urlsplit(decoded)
        except ValueError:
            return None
        return None if parsed.scheme or parsed.netloc else target

    @staticmethod
    def resolve(user, target=None):
        target = LandingService.safe_next(target)
        if user.family_id is None:
            if target and urlsplit(unquote(target)).path.rstrip('/') not in (
                '', '/hub', '/dashboard',
            ):
                return target
            return url_for('auth.account_security')
        if target:
            return target
        return url_for(LandingService.WORKSPACES[LandingService.workspace_for(user)][1])
