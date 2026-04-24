"""
Celery application configuration for HeatGlow CRM backend.

Workers are started with:
    celery -A config worker -l info
    celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""
import os
from celery import Celery

# Tell Celery which Django settings module to use
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('heatglow')

# Read Celery config from Django settings (keys prefixed with CELERY_)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py in every installed app
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Utility task — prints the request info. Used to verify Celery is working."""
    print(f'Request: {self.request!r}')