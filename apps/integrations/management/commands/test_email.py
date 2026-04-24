"""
Send a test email to verify Resend is configured.

Usage:
    python manage.py test_email
    python manage.py test_email --to gareth@heatglow.co.uk
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = 'Send a test email via Resend to verify configuration.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            default=settings.GARETH_EMAIL,
            help='Recipient email address',
        )

    def handle(self, *args, **opts):
        from apps.integrations.resend_client import send_test_email

        to = opts['to']
        self.stdout.write(f'Sending test email to {to}...')

        result = send_test_email(to)

        if result.success:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Test email sent successfully. Resend ID: {result.email_id}'
            ))
        else:
            raise CommandError(f'Failed to send test email: {result.error}')