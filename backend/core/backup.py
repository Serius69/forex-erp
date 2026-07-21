import os
import gzip
import shutil
import glob
import subprocess
from datetime import datetime
from django.conf import settings


class BackupManager:
    """Backup de PostgreSQL con pg_dump.

    Destino local PERSISTENTE (bind-mount al host) — antes escribía en /tmp del
    contenedor, que es efímero: un `docker compose up --force-recreate` borraba
    todos los respaldos. Ahora:
      · BACKUP_DIR (settings/env, default /app/backups, montado en ./backend/backups)
      · comprime con gzip (los dumps SQL bajan ~5-10x)
      · retención: conserva los últimos BACKUP_KEEP (default 7) y borra el resto
      · si hay credenciales AWS, además sube a S3
    """

    @staticmethod
    def _backup_dir() -> str:
        d = getattr(settings, 'BACKUP_DIR', None) or os.environ.get('BACKUP_DIR', '/app/backups')
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _prune(directory: str, keep: int) -> int:
        """Deja solo los `keep` backups más recientes; devuelve cuántos borró."""
        files = sorted(
            glob.glob(os.path.join(directory, 'backup_*.sql.gz')),
            key=os.path.getmtime,
            reverse=True,
        )
        removed = 0
        for old in files[keep:]:
            try:
                os.remove(old)
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def create_and_upload() -> dict:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = BackupManager._backup_dir()
        sql_path = os.path.join(backup_dir, f'backup_{timestamp}.sql')
        gz_path = sql_path + '.gz'

        db = settings.DATABASES['default']
        env = os.environ.copy()
        env['PGPASSWORD'] = db.get('PASSWORD', '')

        cmd = [
            'pg_dump',
            '-h', db.get('HOST', 'localhost'),
            '-p', str(db.get('PORT') or 5432),
            '-U', db.get('USER', 'postgres'),
            '-d', db.get('NAME', 'forex_erp'),
            '-f', sql_path,
            '--no-password',
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            # limpiar un dump parcial si quedó
            if os.path.exists(sql_path):
                os.remove(sql_path)
            raise RuntimeError(f'pg_dump error: {result.stderr}')

        # Comprimir y borrar el .sql plano
        with open(sql_path, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(sql_path)

        keep = int(getattr(settings, 'BACKUP_KEEP', os.environ.get('BACKUP_KEEP', 7)) or 7)
        pruned = BackupManager._prune(backup_dir, keep)
        size_kb = round(os.path.getsize(gz_path) / 1024, 1)

        # S3 opcional: sin credenciales AWS se queda en el backup local persistente.
        aws_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
        if aws_key:
            import boto3
            s3_key = f'backups/{os.path.basename(gz_path)}'
            s3 = boto3.client(
                's3',
                aws_access_key_id=aws_key,
                aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
            )
            s3.upload_file(gz_path, getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None), s3_key)
            return {'status': 'ok', 'file': gz_path, 'size_kb': size_kb,
                    'storage': 's3+local', 's3_key': s3_key, 'pruned': pruned, 'kept': keep}

        return {'status': 'ok', 'file': gz_path, 'size_kb': size_kb,
                'storage': 'local', 'pruned': pruned, 'kept': keep}
