"""
Management command to seed the database with realistic mock data.
Mirrors the exact data shape that ServiceM8 would provide.

Usage:
    python manage.py seed_mock_data
    python manage.py seed_mock_data --customers 100 --jobs 300
    python manage.py seed_mock_data --clear

When real SM8 API access is restored, run:
    python manage.py seed_mock_data --clear
    python manage.py sm8_full_import   (Step 4 command)
"""
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.customers.models import Customer, JobCache


# ── realistic UK data pools ───────────────────────────────────────────────────

FIRST_NAMES = [
    'James', 'Oliver', 'Harry', 'Jack', 'George', 'Noah', 'Charlie', 'Jacob',
    'Alfie', 'Freddie', 'Poppy', 'Olivia', 'Emily', 'Isla', 'Ava', 'Mia',
    'Isabella', 'Sophie', 'Grace', 'Lily', 'Thomas', 'William', 'Edward',
    'Henry', 'Arthur', 'Muhammad', 'Ethan', 'Joshua', 'Daniel', 'Samuel',
    'Gareth', 'Rhys', 'Dylan', 'Liam', 'Owen', 'Cerys', 'Sian', 'Bethan',
]

LAST_NAMES = [
    'Jones', 'Williams', 'Davies', 'Evans', 'Thomas', 'Roberts', 'Hughes',
    'Lewis', 'Morgan', 'Griffiths', 'Wilson', 'Taylor', 'Brown', 'Davies',
    'Smith', 'Price', 'Phillips', 'Edwards', 'Jenkins', 'Rees', 'Powell',
    'Wood', 'Ward', 'Owen', 'Cooper', 'Collins', 'Morris', 'Bailey',
    'Walsh', 'Turner', 'Carter', 'Harris', 'Martin', 'Clarke', 'Green',
]

# Cardiff and surrounding postcodes (matches HeatGlow service area)
POSTCODES = [
    'CF3 1AA', 'CF3 2BB', 'CF3 3CC', 'CF5 1AB', 'CF5 2BC', 'CF5 3CD',
    'CF10 1AA', 'CF10 2BB', 'CF10 3CC', 'CF11 1AB', 'CF11 2BC', 'CF11 6NP',
    'CF14 1AA', 'CF14 2BB', 'CF14 3CC', 'CF14 7BR', 'CF14 4DD', 'CF14 5EE',
    'CF15 1AB', 'CF15 2BC', 'CF15 3CD', 'CF23 1AA', 'CF23 5BB', 'CF23 9BH',
    'CF24 1AB', 'CF24 2BC', 'CF24 3CD', 'CF38 1AA', 'CF38 2BB', 'CF38 3CC',
    'CF62 1AB', 'CF62 2BC', 'CF63 1AA', 'CF63 2BB', 'CF64 1AB', 'CF64 2BC',
    'CF83 1AA', 'CF83 2BB', 'CF83 3CC', 'NP10 1AA', 'NP20 2BB', 'NP44 3CC',
]

STREETS = [
    'Park Road', 'Church Street', 'High Street', 'Victoria Road', 'King Street',
    'Queen Street', 'Station Road', 'Mill Lane', 'School Lane', 'The Green',
    'Manor Road', 'Cedar Avenue', 'Oak Drive', 'Birch Close', 'Elm Way',
    'Heol-y-Coed', 'Ffordd Las', 'Lon Wen', 'Heol Isaf', 'Stryd Fawr',
    'Cardiff Road', 'Newport Road', 'Caerphilly Road', 'Cowbridge Road',
]

CITIES = [
    'Cardiff', 'Cardiff', 'Cardiff', 'Cardiff',  # weighted heavier
    'Penarth', 'Barry', 'Caerphilly', 'Newport',
    'Pontypridd', 'Bridgend', 'Whitchurch', 'Llandaff',
]

EMAIL_DOMAINS = [
    'gmail.com', 'gmail.com', 'gmail.com',   # most common
    'hotmail.com', 'hotmail.co.uk',
    'outlook.com', 'yahoo.co.uk',
    'btinternet.com', 'sky.com', 'talktalk.net',
    'icloud.com',
]

JOB_TYPES = [
    'Boiler Service',
    'Boiler Repair',
    'Boiler Installation',
    'Central Heating Repair',
    'Central Heating Installation',
    'Radiator Installation',
    'Radiator Repair',
    'Hot Water Cylinder',
    'Bathroom Installation',
    'Emergency Plumbing',
    'Leak Repair',
    'Drain Unblocking',
    'Gas Safety Certificate',
    'Landlord Gas Safety',
    'Power Flush',
    'Thermostat Replacement',
    'Pipe Repair',
    'Tap Replacement',
    'Shower Installation',
    'HeatShield Annual Service',
]

JOB_STATUSES = [
    ('Completed', 0.38),
    ('Quote', 0.20),
    ('Invoice Sent', 0.12),
    ('Paid', 0.14),
    ('Work Order', 0.08),
    ('Pending Approval', 0.04),
    ('Cancelled', 0.04),
]

JOB_DESCRIPTIONS = [
    'Annual boiler service and safety check.',
    'Customer reported no hot water. Diagnosed faulty diverter valve.',
    'Full boiler replacement — old unit beyond economic repair.',
    'Radiator not heating in master bedroom. Balanced system.',
    'Emergency call-out: burst pipe under kitchen sink.',
    'Quoted for full central heating installation in new build.',
    'Gas safety certificate required for rental property.',
    'Power flush to clear sludge buildup in system.',
    'New combi boiler installation including full system flush.',
    'Leaking radiator valve replaced in living room.',
    'Thermostat stopped working — replaced with Nest unit.',
    'Annual HeatShield maintenance visit.',
    'Blocked drain in bathroom. Cleared and tested.',
    'New shower installation in en-suite.',
    'Landlord gas safety inspection — 3 appliances checked.',
    'Customer has no heating. Reset boiler, cleaned filter.',
    'Quoted for bathroom renovation including new suite.',
    'Hot water cylinder replaced like-for-like.',
    'Pressure relief valve dripping — replaced.',
    'Expansion vessel failed — replaced and system re-pressurised.',
]


# ── helpers ───────────────────────────────────────────────────────────────────

def random_date(years_back: int = 3) -> date:
    """Return a random date within the last N years."""
    days_back = random.randint(0, years_back * 365)
    return date.today() - timedelta(days=days_back)


def weighted_choice(choices: list[tuple]) -> str:
    """Pick from a list of (value, weight) tuples."""
    values, weights = zip(*choices)
    return random.choices(values, weights=weights, k=1)[0]


def make_email(first: str, last: str, used: set) -> str | None:
    """Generate a plausible email, or None (some customers have no email)."""
    if random.random() < 0.12:   # 12% have no email on file
        return None
    domain = random.choice(EMAIL_DOMAINS)
    variants = [
        f'{first.lower()}.{last.lower()}@{domain}',
        f'{first.lower()}{last.lower()}{random.randint(1, 99)}@{domain}',
        f'{first[0].lower()}{last.lower()}@{domain}',
        f'{last.lower()}{first[0].lower()}@{domain}',
    ]
    for email in variants:
        if email not in used:
            used.add(email)
            return email
    # Fallback with UUID suffix to guarantee uniqueness
    fallback = f'{first.lower()}.{last.lower()}.{uuid.uuid4().hex[:6]}@{domain}'
    used.add(fallback)
    return fallback


def invoice_amount(job_type: str, status: str) -> Decimal:
    """Return a realistic invoice amount for a job type."""
    ranges = {
        'Boiler Installation':          (1800, 3500),
        'Boiler Service':               (80, 150),
        'Boiler Repair':                (150, 600),
        'Central Heating Installation': (2500, 6000),
        'Central Heating Repair':       (100, 450),
        'Bathroom Installation':        (2000, 5000),
        'Gas Safety Certificate':       (60, 90),
        'Landlord Gas Safety':          (70, 100),
        'Power Flush':                  (300, 600),
        'Emergency Plumbing':           (150, 500),
        'HeatShield Annual Service':    (10, 10),
    }
    low, high = ranges.get(job_type, (80, 800))
    amount = Decimal(str(round(random.uniform(low, high), 2)))
    # Quotes and pending items might have £0 (no invoice yet)
    if status in ('Quote', 'Pending Approval') and random.random() < 0.4:
        return Decimal('0.00')
    return amount


# ── main command ─────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Seed the database with realistic mock ServiceM8 data for development.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--customers',
            type=int,
            default=3725,
            help='Number of customers to create (default: 3725 — matches real SM8 count)',
        )
        parser.add_argument(
            '--jobs',
            type=int,
            default=9000,
            help='Number of jobs to create (default: 9000)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing mock data before seeding.',
        )

    def handle(self, *args, **opts):
        customer_count: int = opts['customers']
        job_count: int = opts['jobs']
        clear: bool = opts['clear']

        if clear:
            self.stdout.write(self.style.WARNING('Clearing existing customer and job data...'))
            JobCache.objects.all().delete()
            Customer.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared.\n'))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\nSeeding {customer_count} customers and {job_count} jobs...\n'
        ))

        customers = self._seed_customers(customer_count)
        self._seed_jobs(customers, job_count)
        self._print_summary()

    # ── customers ────────────────────────────────────────────────────────────

    def _seed_customers(self, count: int) -> list[Customer]:
        self.stdout.write(f'Creating {count} customers...')
        used_emails: set[str] = set()
        to_create = []

        for i in range(count):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            postcode = random.choice(POSTCODES)
            city = random.choice(CITIES)
            street_num = random.randint(1, 200)
            street = random.choice(STREETS)

            to_create.append(Customer(
                sm8_company_uuid=uuid.uuid4(),
                name=f'{first} {last}',
                email=make_email(first, last, used_emails),
                phone=self._random_phone(),
                address_line1=f'{street_num} {street}',
                city=city,
                postcode=postcode,
                # Enrichment fields — will be recalculated after jobs seeded
                total_spend=Decimal('0.00'),
                job_count=0,
                heatshield_status=Customer.HeatshieldStatus.NONE,
                sm8_synced_at=timezone.now(),
            ))

            if (i + 1) % 500 == 0:
                self.stdout.write(f'  {i + 1}/{count}...')

        # Bulk insert in batches of 500
        customers_saved = []
        for i in range(0, len(to_create), 500):
            batch = to_create[i:i + 500]
            customers_saved.extend(Customer.objects.bulk_create(batch))

        self.stdout.write(self.style.SUCCESS(f'  ✓ {len(customers_saved)} customers created'))
        return customers_saved

    # ── jobs ─────────────────────────────────────────────────────────────────

    def _seed_jobs(self, customers: list[Customer], count: int) -> None:
        self.stdout.write(f'Creating {count} jobs...')
        to_create = []

        # Weight job distribution — some customers have many jobs, most have few
        # This mirrors real-world data: loyal customers vs one-time callers
        customer_weights = [
            random.choices([1, 2, 3, 5, 8], weights=[40, 25, 20, 10, 5])[0]
            for _ in customers
        ]
        total_weight = sum(customer_weights)
        customer_pool = random.choices(customers, weights=customer_weights, k=count)

        for i, customer in enumerate(customer_pool):
            job_type = random.choice(JOB_TYPES)
            status = weighted_choice(JOB_STATUSES)
            amount = invoice_amount(job_type, status)
            created = random_date(years_back=3)

            # Completed/paid jobs have a completion date
            if status in ('Completed', 'Invoice Sent', 'Paid', 'Work Order'):
                completion = created + timedelta(days=random.randint(0, 14))
                if completion > date.today():
                    completion = date.today()
            else:
                completion = None

            # Quotes have a quote date
            quote_date = created if status == 'Quote' else None

            to_create.append(JobCache(
                sm8_job_uuid=uuid.uuid4(),
                customer=customer,
                sm8_company_uuid=customer.sm8_company_uuid,
                status=status,
                job_address=customer.address_line1,
                job_description=random.choice(JOB_DESCRIPTIONS),
                job_type=job_type,
                total_invoice_amount=amount,
                materials_cost=round(amount * Decimal('0.3'), 2) if amount else Decimal('0'),
                created_date=created,
                completed_date=completion,
                quote_date=quote_date,
                active=True,
                sm8_synced_at=timezone.now(),
            ))

            if (i + 1) % 1000 == 0:
                self.stdout.write(f'  {i + 1}/{count}...')

        # Bulk insert in batches of 500
        for i in range(0, len(to_create), 500):
            JobCache.objects.bulk_create(to_create[i:i + 500])

        self.stdout.write(self.style.SUCCESS(f'  ✓ {count} jobs created'))

        # Recalculate enrichment fields on each customer
        self.stdout.write('Calculating customer spend + job counts...')
        self._recalculate_customer_metrics(customers)

    # ── enrichment ───────────────────────────────────────────────────────────

    def _recalculate_customer_metrics(self, customers: list[Customer]) -> None:
        """
        Update total_spend, job_count, last_job_date, last_job_type
        on every customer from their jobs. Mirrors what
        calculate_customer_metrics() will do in production.
        """
        completed_statuses = ['Completed', 'Invoice Sent', 'Paid', 'Work Order']
        to_update = []

        for i, customer in enumerate(customers):
            jobs = list(customer.jobs.filter(status__in=completed_statuses))
            if not jobs:
                continue

            total = sum(j.total_invoice_amount for j in jobs)
            last_job = max(jobs, key=lambda j: j.completed_date or date.min)

            customer.total_spend = total
            customer.job_count = len(jobs)
            customer.last_job_date = last_job.completed_date
            customer.last_job_type = last_job.job_type
            to_update.append(customer)

            if (i + 1) % 500 == 0:
                self.stdout.write(f'  {i + 1}/{len(customers)}...')

        Customer.objects.bulk_update(
            to_update,
            ['total_spend', 'job_count', 'last_job_date', 'last_job_type'],
            batch_size=500,
        )
        self.stdout.write(self.style.SUCCESS(
            f'  ✓ Enrichment calculated for {len(to_update)} customers'
        ))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _random_phone(self) -> str:
        """Generate a realistic UK phone number."""
        prefixes = ['07700', '07711', '07722', '07733', '07744',
                    '07811', '07900', '07955', '07977', '07999',
                    '02920', '02921', '01443', '01446', '01222']
        prefix = random.choice(prefixes)
        suffix = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        return f'{prefix} {suffix[:3]} {suffix[3:]}'

    def _print_summary(self) -> None:
        """Print a summary of what was created."""
        from django.db.models import Sum, Count

        total_customers = Customer.objects.count()
        total_jobs = JobCache.objects.count()
        total_revenue = JobCache.objects.filter(
            status__in=['Completed', 'Invoice Sent', 'Paid']
        ).aggregate(t=Sum('total_invoice_amount'))['t'] or 0

        status_breakdown = (
            JobCache.objects
            .values('status')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        self.stdout.write(self.style.MIGRATE_HEADING('\n── Summary ──────────────────────'))
        self.stdout.write(f'  Customers:      {total_customers:,}')
        self.stdout.write(f'  Jobs:           {total_jobs:,}')
        self.stdout.write(f'  Total revenue:  £{total_revenue:,.2f}')
        self.stdout.write('\n  Jobs by status:')
        for row in status_breakdown:
            self.stdout.write(f'    {row["status"]:<25} {row["count"]:,}')

        self.stdout.write(self.style.SUCCESS(
            '\n✓ Mock data ready. Django admin at http://127.0.0.1:8000/admin/\n'
        ))