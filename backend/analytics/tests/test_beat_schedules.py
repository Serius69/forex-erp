# analytics/tests/test_beat_schedules.py
"""
Verifica que la data migration analytics.0007 pobló django_celery_beat
con el beat_schedule EFECTIVO de Celery (CELERY_BEAT_SCHEDULE de settings,
que tiene prioridad sobre core/celery.py) para instalación limpia.

El test-DB se crea corriendo TODAS las migraciones, así que las filas
de PeriodicTask ya deben existir aquí.
"""
from django.test import TestCase

from django_celery_beat.models import PeriodicTask


class CeleryBeatMigrationTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from core.celery import app as celery_app
        cls.beat_schedule = celery_app.conf.beat_schedule

    def test_todas_las_entradas_del_beat_schedule_existen(self):
        nombres_db = set(
            PeriodicTask.objects.values_list('name', flat=True)
        )
        faltantes = set(self.beat_schedule.keys()) - nombres_db
        self.assertEqual(faltantes, set(),
                         f'Schedules sin poblar en DB: {sorted(faltantes)}')

    def test_entrada_interval_espeja_task_y_periodo(self):
        # rates-binance-p2p: cada 5 min (300 s), cola high
        entry = self.beat_schedule['rates-binance-p2p']
        pt = PeriodicTask.objects.get(name='rates-binance-p2p')

        self.assertEqual(pt.task, entry['task'])
        self.assertTrue(pt.enabled)
        self.assertIsNotNone(pt.interval)
        self.assertEqual(pt.interval.every, 300)
        self.assertEqual(pt.interval.period, 'seconds')
        self.assertEqual(pt.queue, 'high')

    def test_entrada_crontab_espeja_horario(self):
        # rates-daily-snapshot: cierre de operaciones 18:00 Bolivia
        pt = PeriodicTask.objects.get(name='rates-daily-snapshot')
        self.assertIsNotNone(pt.crontab)
        self.assertEqual(pt.crontab.hour, '18')
        self.assertEqual(pt.crontab.minute, '0')
        self.assertEqual(str(pt.crontab.timezone), 'America/La_Paz')

    def test_no_quedan_tareas_sin_schedule(self):
        # Toda entrada poblada por la migración debe tener crontab o interval
        pobladas = PeriodicTask.objects.filter(
            name__in=list(self.beat_schedule.keys())
        )
        for pt in pobladas:
            self.assertTrue(
                pt.crontab_id or pt.interval_id,
                f'{pt.name} quedó sin crontab ni interval',
            )
