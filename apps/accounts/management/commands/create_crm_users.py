"""
Creates the two CRM users — Gareth (admin) and Rebecca (staff).
Safe to run multiple times — uses get_or_create.

Usage:
    python manage.py create_crm_users
    python manage.py create_crm_users --gareth-password mypassword
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from apps.accounts.models import UserProfile


class Command(BaseCommand):
    help = 'Create Gareth (admin) and Rebecca (staff) CRM user accounts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--gareth-password',
            default='heatglow-gareth-2026',
            help='Password for Gareth\'s account',
        )
        parser.add_argument(
            '--rebecca-password',
            default='heatglow-rebecca-2026',
            help='Password for Rebecca\'s account',
        )

    def handle(self, *args, **opts):
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\nCreating CRM users...\n'
        ))

        gareth = self._create_user(
            username='gareth',
            email='gareth@heatglow.co.uk',
            first_name='Gareth',
            last_name='Jones',
            password=opts['gareth_password'],
            role=UserProfile.Role.ADMIN,
        )

        rebecca = self._create_user(
            username='rebecca',
            email='rebecca@heatglow.co.uk',
            first_name='Rebecca',
            last_name='Admin',
            password=opts['rebecca_password'],
            role=UserProfile.Role.STAFF,
        )

        self.stdout.write(self.style.SUCCESS('\n✓ Users ready.\n'))
        self.stdout.write('  Gareth  → username: gareth   role: admin')
        self.stdout.write(f'           password: {opts["gareth_password"]}')
        self.stdout.write('  Rebecca → username: rebecca  role: staff')
        self.stdout.write(f'           password: {opts["rebecca_password"]}')
        self.stdout.write(
            '\nChange passwords before going to production!\n'
        )

    def _create_user(
        self, username, email, first_name, last_name, password, role
    ) -> User:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
                'is_staff': role == UserProfile.Role.ADMIN,
                'is_superuser': role == UserProfile.Role.ADMIN,
            },
        )

        if created:
            user.set_password(password)
            user.save()
            action = 'Created'
        else:
            action = 'Already exists'

        # Create or update the profile
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={'role': role},
        )
        if not _:
            profile.role = role
            profile.save()

        self.stdout.write(f'  {action}: {username} ({role})')
        return user