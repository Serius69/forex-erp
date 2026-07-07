# Data migration — puebla django_celery_beat (PeriodicTask + Crontab/Interval)
# a partir del beat_schedule EFECTIVO de la app Celery, para que una
# instalación limpia tenga los schedules en DB sin esperar al primer
# arranque de beat.
#
# Nota: el schedule efectivo es CELERY_BEAT_SCHEDULE de core/settings/base.py
# (config_from_object namespace='CELERY'), que tiene prioridad sobre el
# beat_schedule asignado en core/celery.py. Aquí iteramos app.conf.beat_schedule
# para espejar exactamente lo que beat ejecutaría.
#
# Vive en `analytics` porque `core` (donde se define el schedule) no es una
# app Django instalada. Usa los modelos reales de django_celery_beat (no
# apps.get_model) porque son de terceros y la dependencia explícita a su
# última migración garantiza el esquema completo.

from datetime import timedelta
from numbers import Number

from django.db import migrations

BEAT_TIMEZONE = 'America/La_Paz'  # = CELERY_TIMEZONE en core/settings/base.py


def _iter_beat_schedule():
    from core.celery import app as celery_app
    return celery_app.conf.beat_schedule.items()


def _get_schedule_fk(schedule):
    """Devuelve (campo, objeto) para PeriodicTask según el tipo de schedule."""
    from celery.schedules import crontab as celery_crontab
    from celery.schedules import schedule as celery_schedule
    from django_celery_beat.models import CrontabSchedule, IntervalSchedule

    if isinstance(schedule, celery_crontab):
        cron, _ = CrontabSchedule.objects.get_or_create(
            minute=str(schedule._orig_minute),
            hour=str(schedule._orig_hour),
            day_of_week=str(schedule._orig_day_of_week),
            day_of_month=str(schedule._orig_day_of_month),
            month_of_year=str(schedule._orig_month_of_year),
            timezone=BEAT_TIMEZONE,
        )
        return 'crontab', cron

    # Intervalos: segundos (int/float), timedelta o celery.schedules.schedule
    seconds = None
    if isinstance(schedule, Number):
        seconds = int(schedule)
    elif isinstance(schedule, timedelta):
        seconds = int(schedule.total_seconds())
    elif isinstance(schedule, celery_schedule):
        seconds = int(schedule.run_every.total_seconds())

    if seconds:
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=seconds, period=IntervalSchedule.SECONDS,
        )
        return 'interval', interval

    return None, None


def populate_schedules(apps, schema_editor):
    from django_celery_beat.models import PeriodicTask

    for name, entry in _iter_beat_schedule():
        field, schedule_obj = _get_schedule_fk(entry.get('schedule'))
        if field is None:
            continue  # tipo de schedule no soportado (solar/clocked no se usan)

        options = entry.get('options', {}) or {}
        expires = options.get('expires')

        defaults = {
            'task':           entry['task'],
            'crontab':        None,
            'interval':       None,
            'solar':          None,
            'clocked':        None,
            'queue':          options.get('queue'),
            'expire_seconds': int(expires) if expires else None,
            'enabled':        True,
            'description':    'Poblado por data migration analytics.0007 '
                              '(fuente: beat_schedule efectivo de Celery).',
        }
        defaults[field] = schedule_obj

        PeriodicTask.objects.update_or_create(name=name, defaults=defaults)


def remove_schedules(apps, schema_editor):
    from django_celery_beat.models import PeriodicTask

    names = [name for name, _ in _iter_beat_schedule()]
    PeriodicTask.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0006_add_decision_log'),
        ('django_celery_beat', '0018_improve_crontab_helptext'),
    ]

    operations = [
        migrations.RunPython(populate_schedules, remove_schedules),
    ]
