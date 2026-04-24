"""
Test the Gemini scoring with sample enquiries.

Usage:
    python manage.py test_gemini
"""
from django.core.management.base import BaseCommand, CommandError
from apps.integrations.gemini import qualify_enquiry


class Command(BaseCommand):
    help = 'Test Gemini enquiry qualification with sample data.'

    def handle(self, *args, **opts):
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n=== Gemini qualification test ===\n'
        ))

        test_cases = [
            {
                'label': 'Routine boiler service in Cardiff (should APPROVE ~85)',
                'customer_name': 'John Williams',
                'postcode': 'CF14 7BR',
                'job_type': 'Boiler Service',
                'urgency': 'routine',
                'description': (
                    'Annual boiler service required. Worcester Bosch combi boiler '
                    'installed 2018. Needs its annual service and gas safety check.'
                ),
            },
            {
                'label': 'Emergency burst pipe in Newport (should APPROVE ~90+)',
                'customer_name': 'Sarah Jones',
                'postcode': 'NP20 2BB',
                'job_type': 'Emergency Plumbing',
                'urgency': 'emergency',
                'description': (
                    'Burst pipe under kitchen sink. Water coming through the '
                    'ceiling below. Stopcock turned off. Need urgent help today.'
                ),
            },
            {
                'label': 'Out of area — London (should REJECT ~15)',
                'customer_name': 'Bob Smith',
                'postcode': 'SW1A 1AA',
                'job_type': 'Boiler Repair',
                'urgency': 'urgent',
                'description': 'Boiler stopped working. No heating or hot water.',
            },
            {
                'label': 'Commercial restaurant job (should REJECT ~20)',
                'customer_name': 'Cardiff Restaurant Ltd',
                'postcode': 'CF10 3AT',
                'job_type': 'Central Heating',
                'urgency': 'routine',
                'description': (
                    'We need full commercial kitchen extraction and heating '
                    'system installed for our new restaurant opening next month. '
                    'Large commercial property, 3 floors.'
                ),
            },
            {
                'label': 'Vague description (should be MANUAL_REVIEW ~45)',
                'customer_name': 'Mike Davis',
                'postcode': 'CF23 9BH',
                'job_type': 'Plumbing',
                'urgency': 'flexible',
                'description': 'Need some plumbing work done.',
            },
        ]

        for i, case in enumerate(test_cases, 1):
            self.stdout.write(f'\n[{i}] {case["label"]}')
            self.stdout.write(f'    Postcode: {case["postcode"]} | Job: {case["job_type"]} | Urgency: {case["urgency"]}')

            try:
                result = qualify_enquiry(
                    customer_name=case['customer_name'],
                    postcode=case['postcode'],
                    job_type=case['job_type'],
                    urgency=case['urgency'],
                    description=case['description'],
                )

                score_bar = '█' * (result.score // 10) + '░' * (10 - result.score // 10)
                self.stdout.write(
                    f'    Score:          {result.score}/100  [{score_bar}]'
                )
                self.stdout.write(
                    f'    Recommendation: {result.recommendation}'
                )
                self.stdout.write(
                    f'    Confidence:     {result.confidence}'
                )
                self.stdout.write(
                    f'    Explanation:    {result.explanation}'
                )
                if result.flags:
                    self.stdout.write(
                        f'    Flags:          {", ".join(result.flags)}'
                    )

            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f'    FAILED: {exc}')
                )

        self.stdout.write(self.style.SUCCESS(
            '\n✓ Test complete. Check scores match the expected ranges above.\n'
        ))