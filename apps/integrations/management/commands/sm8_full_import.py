"""
One-time full import from ServiceM8 into the database.
Run this once when the SM8 API key is working to replace mock data.

Usage:
    python manage.py sm8_full_import
    python manage.py sm8_full_import --dry-run
"""
from django.core.management.base import BaseCommand, CommandError
from apps.integrations.sm8.client import SM8Client, SM8Error
from apps.integrations.sync import sync_companies, sync_jobs
from apps.core.models import SyncLog
from django.utils import timezone


class Command(BaseCommand):
    help = 'Full one-time import of all ServiceM8 customers and jobs.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Fetch from SM8 but do not write to database.',
        )

    def handle(self, *args, **opts):
        dry_run = opts['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no database writes\n'))

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n=== ServiceM8 full import ===\n'
        ))

        sync_log = SyncLog.objects.create(
            sync_type=SyncLog.SyncType.SM8_FULL,
            status=SyncLog.Status.RUNNING,
        )

        try:
            with SM8Client() as client:
                self.stdout.write('Syncing companies...')
                if not dry_run:
                    companies = sync_companies(client)
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ {companies} companies synced')
                    )
                else:
                    count = sum(1 for c in client.iter_companies() if c.active == 1)
                    self.stdout.write(f'  Would sync {count} active companies')

                self.stdout.write('Syncing jobs...')
                if not dry_run:
                    jobs = sync_jobs(client)
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ {jobs} jobs synced')
                    )
                else:
                    count = sum(1 for _ in client.iter_jobs())
                    self.stdout.write(f'  Would sync {count} jobs')

            if not dry_run:
                sync_log.status = SyncLog.Status.SUCCESS
                sync_log.records_synced = companies + jobs
                sync_log.finished_at = timezone.now()
                sync_log.save()
                self.stdout.write(self.style.SUCCESS(
                    '\n✓ Import complete. Run seed_mock_data --clear first '
                    'if you had mock data.\n'
                ))

        except SM8Error as exc:
            sync_log.status = SyncLog.Status.FAIL
            sync_log.error_detail = str(exc)
            sync_log.finished_at = timezone.now()
            sync_log.save()
            raise CommandError(f'SM8 error: {exc}') from exc