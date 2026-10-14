import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from urllib.parse import urlsplit

from flask import current_app, has_request_context, render_template, url_for


class EmailService:
	"""Plain-text transactional email over SMTP. Does nothing until MAIL_SERVER is configured."""

	@staticmethod
	def is_configured():
		return bool(current_app.config.get('MAIL_SERVER') and current_app.config.get('MAIL_FROM'))

	@staticmethod
	def external_url(endpoint, **values):
		"""Absolute link for emails, built from APP_BASE_URL rather than the request's Host header."""
		base = current_app.config.get('APP_BASE_URL')
		if base:
			parts = urlsplit(base)
			adapter = current_app.url_map.bind(parts.netloc, script_name=parts.path or '/', url_scheme=parts.scheme)
			return adapter.build(endpoint, values, force_external=True)
		if has_request_context():
			return url_for(endpoint, _external=True, **values)
		raise ValueError('Set APP_BASE_URL so emailed links point at your site.')

	@staticmethod
	def outbox():
		"""Messages captured instead of sent while testing."""
		return current_app.extensions.setdefault('mail_outbox', [])

	@staticmethod
	def send(to, subject, template, wait=False, **context):
		"""Render templates/email/<template>.txt and send it.

		Returns False if email is not configured. By default delivery happens in the background
		and failures are only logged; wait=True delivers now and raises on failure.
		"""
		if not EmailService.is_configured():
			return False
		app = current_app._get_current_object()
		message = EmailMessage()
		message['Subject'] = subject
		message['From'] = app.config['MAIL_FROM']
		message['To'] = to
		message['Date'] = formatdate(localtime=False, usegmt=True)
		sender_domain = app.config['MAIL_FROM'].rsplit('@', 1)[-1].strip(' >') or None
		message['Message-ID'] = make_msgid(domain=sender_domain)
		message.set_content(render_template(f'email/{template}.txt', **context))

		if app.testing:
			EmailService.outbox().append(message)
			return True
		if wait:
			EmailService._deliver(app, message)
			return True
		if not has_request_context():
			# CLI commands exit straight away, which would kill a background thread mid-send.
			EmailService._deliver_in_background(app, message)
			return True
		threading.Thread(target=EmailService._deliver_in_background, args=(app, message), daemon=True).start()
		return True

	@staticmethod
	def _deliver_in_background(app, message):
		try:
			EmailService._deliver(app, message)
		except Exception:
			app.logger.exception('Failed to send email "%s"', message['Subject'])

	@staticmethod
	def _deliver(app, message):
		config = app.config
		timeout = config.get('MAIL_TIMEOUT_SECONDS', 15)
		tls_context = ssl.create_default_context()
		if config.get('MAIL_USE_SSL'):
			smtp = smtplib.SMTP_SSL(config['MAIL_SERVER'], config['MAIL_PORT'], timeout=timeout, context=tls_context)
		else:
			smtp = smtplib.SMTP(config['MAIL_SERVER'], config['MAIL_PORT'], timeout=timeout)
		with smtp:
			if config.get('MAIL_USE_TLS'):
				smtp.starttls(context=tls_context)
			if config.get('MAIL_USERNAME'):
				smtp.login(config['MAIL_USERNAME'], config.get('MAIL_PASSWORD', ''))
			smtp.send_message(message)
