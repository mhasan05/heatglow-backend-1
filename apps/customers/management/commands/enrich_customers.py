"""
Management command to enrich all customers from jobs_cache data.
Recalculates metrics and segments for every customer.

Usage:
    python manage.py enrich_customers
    python manage.py enrich_customers --segments-only
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Recalculate customer metrics and segments from jobs_cache.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--segments-only',
            action='store_true',
            help='Only recalculate segments, skip metric enrichment.',
        )

    def handle(self, *args, **opts):
        segments_only = opts['segments_only']

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\nEnriching customers...\n'
        ))

        if not segments_only:
            self._enrich_metrics()

        self._recalculate_segments()

        self.stdout.write(self.style.SUCCESS('\n✓ Enrichment complete.\n'))

    def _enrich_metrics(self):
        """Recalculate spend, job count and last job for every customer."""
        from apps.customers.models import Customer
        from apps.customers.utils import recalculate_customer_metrics

        total = Customer.objects.count()
        self.stdout.write('Enriching metrics for ' + str(total) + ' customers...')

        # Use manual chunking instead of iterator() to avoid
        # psycopg3 server-side cursor issues on Windows
        chunk_size = 200
        offset = 0
        processed = 0

        while True:
            chunk = list(
                Customer.objects.only('id')
                .order_by('id')[offset:offset + chunk_size]
            )
            if not chunk:
                break

            for customer in chunk:
                recalculate_customer_metrics(customer.id)
                processed += 1

            if processed % 500 == 0 or processed == total:
                self.stdout.write('  ' + str(processed) + '/' + str(total) + '...')

            offset += chunk_size

        self.stdout.write(self.style.SUCCESS(
            '  Done: metrics updated for ' + str(processed) + ' customers'
        ))

    def _recalculate_segments(self):
        """Recalculate segment membership for all customers."""
        from apps.customers.segments import recalculate_all_segments

        self.stdout.write('Recalculating segments...')
        result = recalculate_all_segments()

        self.stdout.write(self.style.SUCCESS(
            '  ✓ ' + str(result['updated']) + ' customers updated'
        ))
        self.stdout.write('\n  Segment breakdown:')
        for seg, count in result['segments'].items():
            self.stdout.write(
                '    %-25s %d customers' % (seg, count)
            )