from urllib.parse import unquote, urlsplit

from flask import url_for

from services.platform.module_registry import ModuleRegistry


class LandingService:
    WORKSPACES = ModuleRegistry.default_destinations()

    @staticmethod
    def workspace_for(user):
        workspace = (user.preferences or {}).get('default_workspace', 'central')
        return workspace if workspace in ModuleRegistry.destinations_for(user) else 'central'

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
        if not ModuleRegistry.has_active_household(user):
            if target and urlsplit(unquote(target)).path.rstrip('/') not in (
                '', '/hub', '/dashboard',
            ):
                return target
            return url_for('auth.account_security')
        if target:
            return target
        if user.is_managed_child:
            from services.platform.module_access_service import ModuleAccessService
            if ModuleAccessService.can_access(user, 'household'):
                return url_for('household.my_day')
        return url_for(LandingService.WORKSPACES[LandingService.workspace_for(user)][1])
