"""
Management command to verify the ServiceM8 API connection.

Usage:
    python manage.py sm8_test
    python manage.py sm8_test --companies 5 --jobs 5
    python manage.py sm8_test --count-only
"""
from django.core.management.base import BaseCommand, CommandError

from apps.integrations.sm8.client import SM8Client, SM8Error


class Command(BaseCommand):
    help = 'Test ServiceM8 API connection by fetching real data from Gareth\'s account.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--companies',
            type=int,
            default=3,
            help='Number of companies to preview (default: 3)',
        )
        parser.add_argument(
            '--jobs',
            type=int,
            default=3,
            help='Number of jobs to preview (default: 3)',
        )
        parser.add_argument(
            '--count-only',
            action='store_true',
            help='Only count total records, do not preview individual items.',
        )

    def handle(self, *args, **opts):
        companies_limit: int = opts['companies']
        jobs_limit: int = opts['jobs']
        count_only: bool = opts['count_only']

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n=== ServiceM8 connection test ===\n'
        ))

        try:
            with SM8Client() as client:
                self._test_companies(client, companies_limit, count_only)
                self._test_jobs(client, jobs_limit, count_only)
        except SM8Error as exc:
            raise CommandError(f'SM8 error: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(
            '\n✓ Connection successful. Ready for Step 4 (full import).\n'
        ))

    # ---------- helpers ----------

    def _test_companies(self, client, limit: int, count_only: bool) -> None:
        self.stdout.write(self.style.HTTP_INFO('\n[companies]'))

        companies = client.fetch_all_companies()
        active = [c for c in companies if c.active == 1]

        self.stdout.write(f'  Total fetched:   {len(companies)}')
        self.stdout.write(f'  Active (active=1): {len(active)}')
        self.stdout.write(f'  Archived (active=0): {len(companies) - len(active)}')

        if count_only:
            return

        self.stdout.write(f'\n  First {limit} active companies:')
        for c in active[:limit]:
            self.stdout.write(
                f'    • {c.name:<40} '
                f'{(c.email or "no-email"):<35} '
                f'{(c.postcode or "no-pc"):<10}'
            )

    def _test_jobs(self, client, limit: int, count_only: bool) -> None:
        self.stdout.write(self.style.HTTP_INFO('\n[jobs]'))

        jobs = client.fetch_all_jobs()
        by_status: dict[str, int] = {}
        for j in jobs:
            by_status[j.status] = by_status.get(j.status, 0) + 1

        self.stdout.write(f'  Total jobs:      {len(jobs)}')
        self.stdout.write('  Breakdown by status:')
        for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
            self.stdout.write(f'    {status:<25} {count}')

        if count_only:
            return

        self.stdout.write(f'\n  First {limit} jobs:')
        for j in jobs[:limit]:
            self.stdout.write(
                f'    • {j.status:<18} '
                f'£{j.total_invoice_amount:<10.2f} '
                f'{(j.job_type or "no-type"):<25} '
                f'{(j.completion_date or "not-completed")}'
            )