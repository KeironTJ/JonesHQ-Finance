import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import current_app, session
from sqlalchemy.exc import IntegrityError
from webauthn import (
    generate_authentication_options, generate_registration_options, options_to_json,
    verify_authentication_response, verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
    ResidentKeyRequirement, UserVerificationRequirement,
)

from extensions import db
from models.passkeys import PasskeyChallenge, UserPasskey
from models.users import User
from services.platform.security_event_service import SecurityEventService
from services.platform.user_session_service import UserSessionService


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PasskeyService:
    @staticmethod
    def configuration():
        origin = current_app.config.get('PASSKEY_ORIGIN', '')
        parsed = urlsplit(origin)
        hostname = parsed.hostname
        rp_id = current_app.config.get('PASSKEY_RP_ID') or hostname
        if (
            not hostname or not rp_id or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment
            or (parsed.scheme != 'https' and not (
                parsed.scheme == 'http' and hostname in ('localhost', '127.0.0.1')
            ))
            or not (hostname == rp_id or hostname.endswith('.' + rp_id))
        ):
            raise ValueError('Passkeys need a valid PASSKEY_ORIGIN and matching PASSKEY_RP_ID. Contact the site operator.')
        return rp_id, origin

    @staticmethod
    def is_configured():
        return bool(current_app.config.get('PASSKEY_ORIGIN'))

    @staticmethod
    def _begin(options, purpose, user=None, context=None):
        old_token = session.pop('passkey_flow', None)
        if old_token:
            PasskeyChallenge.query.filter_by(
                token_hash=hashlib.sha256(old_token.encode()).hexdigest(),
            ).delete()
        PasskeyChallenge.query.filter(PasskeyChallenge.expires_at <= _now()).delete()
        token = secrets.token_urlsafe(32)
        db.session.add(PasskeyChallenge(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            challenge=options.challenge, purpose=purpose,
            user_id=user.id if user else None,
            expires_at=_now() + timedelta(minutes=5), context=context or {},
        ))
        db.session.commit()
        session['passkey_flow'] = token
        return json.loads(options_to_json(options))

    @staticmethod
    def _consume(purpose, user=None):
        token = session.pop('passkey_flow', '')
        row = PasskeyChallenge.query.filter_by(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            purpose=purpose, user_id=user.id if user else None,
        ).first()
        if row is None:
            raise ValueError('Your passkey request has expired. Please try again.')
        challenge, context, expires_at = row.challenge, row.context, row.expires_at
        deleted = PasskeyChallenge.query.filter_by(id=row.id).delete()
        db.session.commit()
        if deleted != 1 or expires_at <= _now():
            raise ValueError('Your passkey request has expired. Please try again.')
        return challenge, context

    @staticmethod
    def begin_registration(user, data):
        UserSessionService.require_existing_admin_factor(user)
        rp_id, _ = PasskeyService.configuration()
        name = data.get('name')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise ValueError('Enter a passkey name of 1 to 100 characters.')
        if user.passkeys.count() >= 20:
            raise ValueError('Remove an old passkey before adding another (maximum 20).')
        options = generate_registration_options(
            rp_id=rp_id, rp_name='Family HQ', user_name=user.email,
            user_id=f'familyhq-user-{user.id}'.encode(), user_display_name=user.name,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(key.credential_id))
                for key in user.passkeys.all()
            ],
        )
        return PasskeyService._begin(options, 'register', user, {'name': name.strip()})

    @staticmethod
    def finish_registration(user, data):
        UserSessionService.require_existing_admin_factor(user)
        challenge, context = PasskeyService._consume('register', user)
        rp_id, origin = PasskeyService.configuration()
        try:
            verified = verify_registration_response(
                credential=data, expected_challenge=challenge, expected_rp_id=rp_id,
                expected_origin=origin, require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError) as error:
            SecurityEventService.record('passkey_failed', user=user, details='registration')
            raise ValueError('The passkey could not be verified. Please try again.') from error
        if len(verified.credential_id) > 1023:
            raise ValueError('This passkey is not supported. Please use another authenticator.')
        # Serialize credential changes for one user, including the maximum/last-factor checks.
        User.query.filter_by(id=user.id).update({User.id: User.id}, synchronize_session=False)
        if user.passkeys.count() >= 20:
            db.session.rollback()
            raise ValueError('Remove an old passkey before adding another (maximum 20).')
        key = UserPasskey(
            user_id=user.id, credential_id=bytes_to_base64url(verified.credential_id),
            public_key=verified.credential_public_key, sign_count=verified.sign_count,
            name=context['name'], created_at=_now(),
        )
        db.session.add(key)
        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            current_app.logger.warning('Passkey registration conflicted with an existing credential or account', exc_info=True)
            raise ValueError('That passkey is already registered. Use a different passkey.') from error
        UserSessionService.mark_passkey_authenticated(user)
        UserSessionService.revoke_others(user)
        SecurityEventService.record('passkey_added', user=user, details=key.name)
        return key

    @staticmethod
    def begin_authentication(data, user=None):
        rp_id, _ = PasskeyService.configuration()
        options = generate_authentication_options(
            rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(key.credential_id))
                for key in user.passkeys.all()
            ] if user else None,
        )
        if user and not user.passkeys.count():
            raise ValueError('Register a passkey from Account security first.')
        context = {'remember': data.get('remember') is True, 'next': data.get('next')}
        return PasskeyService._begin(options, 'reauth' if user else 'login', user, context)

    @staticmethod
    def finish_authentication(data, user=None):
        challenge, context = PasskeyService._consume('reauth' if user else 'login', user)
        rp_id, origin = PasskeyService.configuration()
        credential_id = data.get('id')
        key = UserPasskey.query.filter_by(credential_id=credential_id).first() if isinstance(credential_id, str) else None
        account = db.session.get(User, key.user_id) if key else None
        if (
            key is None or account is None or not account.is_active or account.is_locked()
            or (user is not None and account.id != user.id)
        ):
            SecurityEventService.record('passkey_failed', user=user)
            raise ValueError('The passkey could not be verified. Try again or use your password and authenticator.')
        try:
            response = data.get('response', {})
            handle = response.get('userHandle') if isinstance(response, dict) else None
            if handle is not None and not isinstance(handle, str):
                raise ValueError('Invalid user handle')
            if handle is not None and base64url_to_bytes(handle) != f'familyhq-user-{account.id}'.encode():
                raise ValueError('User handle mismatch')
            verified = verify_authentication_response(
                credential=data, expected_challenge=challenge, expected_rp_id=rp_id,
                expected_origin=origin, credential_public_key=key.public_key,
                credential_current_sign_count=key.sign_count, require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError) as error:
            SecurityEventService.record('passkey_failed', user=account)
            raise ValueError('The passkey could not be verified. Please try again.') from error
        updated = UserPasskey.query.filter_by(id=key.id, sign_count=key.sign_count).update(
            {UserPasskey.sign_count: verified.new_sign_count, UserPasskey.last_used_at: _now()},
            synchronize_session='fetch',
        )
        if updated != 1:
            db.session.rollback()
            raise ValueError('The passkey changed during sign-in. Please try again.')
        account.failed_login_attempts = 0
        account.locked_until = None
        account.last_login = _now()
        db.session.commit()
        if user:
            UserSessionService.mark_passkey_authenticated(user)
            SecurityEventService.record('passkey_reauthenticated', user=user)
        return account, context

    @staticmethod
    def remove(user, key_id):
        UserSessionService.require_existing_admin_factor(user)
        User.query.filter_by(id=user.id).update({User.id: User.id}, synchronize_session=False)
        key = user.passkeys.filter_by(id=key_id).first()
        if key is None:
            db.session.rollback()
            raise ValueError('That passkey was not found.')
        if user.is_site_admin and not user.two_factor_enabled and user.passkeys.count() <= 1:
            db.session.rollback()
            raise ValueError('Set up authenticator two-factor login before removing your last passkey.')
        name = key.name
        db.session.delete(key)
        db.session.commit()
        UserSessionService.revoke_others(user)
        SecurityEventService.record('passkey_removed', user=user, details=name)

    @staticmethod
    def reset(user):
        """Server-only recovery when all registered passkeys have been lost."""
        user.passkeys.delete()
        user.passkey_challenges.delete()
        db.session.commit()
        UserSessionService.revoke_all(user, reason='passkeys reset')
        SecurityEventService.record('passkeys_reset', user=user)
