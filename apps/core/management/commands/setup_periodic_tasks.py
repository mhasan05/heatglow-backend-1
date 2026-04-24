"""
Creates all Celery Beat periodic task schedules in the database.
Safe to run multiple times — uses update_or_create.

Usage:
    python manage.py setup_periodic_tasks
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule
import json


class Command(BaseCommand):
    help = 'Register all Celery Beat periodic tasks in the database.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\nSetting up periodic tasks...\n'
        ))

        # ── schedules ────────────────────────────────────────────────────────

        every_hour, _ = IntervalSchedule.objects.get_or_create(
            every=1, period=IntervalSchedule.HOURS,
        )
        every_4_hours, _ = IntervalSchedule.objects.get_or_create(
            every=4, period=IntervalSchedule.HOURS,
        )
        every_15_min, _ = IntervalSchedule.objects.get_or_create(
            every=15, period=IntervalSchedule.MINUTES,
        )

        # Crontab: daily at 09:00 UTC
        daily_9am, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='9',
            day_of_week='*', day_of_month='*', month_of_year='*',
        )
        # Crontab: daily at 02:00 UTC (nightly enrichment)
        daily_2am, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='2',
            day_of_week='*', day_of_month='*', month_of_year='*',
        )
        # Crontab: daily at 06:00 UTC
        daily_6am, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='6',
            day_of_week='*', day_of_month='*', month_of_year='*',
        )

        # ── tasks ────────────────────────────────────────────────────────────

        tasks = [
            {
                'name': 'SM8 incremental sync (hourly)',
                'task': 'integrations.sm8_incremental_sync',
                'interval': every_hour,
                'description': 'Fetches new/changed SM8 records every hour.',
            },
            {
                'name': 'SM8 full sync (4-hourly safety net)',
                'task': 'integrations.sm8_full_sync',
                'interval': every_4_hours,
                'description': 'Full reconciliation sync every 4 hours.',
            },
            {
                'name': 'Process automation queue (every 15 min)',
                'task': 'automation.process_automation_queue',
                'interval': every_15_min,
                'description': 'Dispatches pending AutomationQueue rows via Resend.',
            },
            {
                'name': 'Tier 1 automations (daily 09:00)',
                'task': 'automation.run_tier1_automations',
                'crontab': daily_9am,
                'description': 'HeatShield renewal reminders.',
            },
            {
                'name': 'Recalculate segments (nightly 02:00)',
                'task': 'customers.recalculate_segments',
                'crontab': daily_2am,
                'description': 'Refreshes customer segment membership.',
            },
            {
                'name': 'Tier 2 draft prep (daily 06:00)',
                'task': 'automation.run_tier2_draft_prep',
                'crontab': daily_6am,
                'description': 'Generate Tier 2 campaign drafts for Gareth approval.',
            },
        ]

        for task_def in tasks:
            crontab = task_def.pop('description', None)
            is_crontab = 'crontab' in task_def

            defaults = {
                'enabled': True,
                'one_off': False,
                'args': json.dumps([]),
                'kwargs': json.dumps({}),
            }

            if is_crontab:
                defaults['crontab'] = task_def.pop('crontab')
                if 'interval' in task_def:
                    task_def.pop('interval')
            else:
                defaults['interval'] = task_def.pop('interval')

            obj, created = PeriodicTask.objects.update_or_create(
                name=task_def['name'],
                defaults={**defaults, 'task': task_def['task']},
            )

            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status}: {obj.name}')

        self.stdout.write(self.style.SUCCESS(
            '\n✓ All periodic tasks registered.\n'
            'View them at http://127.0.0.1:8000/admin/django_celery_beat/periodictask/\n'
        ))