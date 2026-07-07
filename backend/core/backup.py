import os
import subprocess
import boto3
from datetime import datetime
from django.conf import settings


class BackupManager:
    @staticmethod
    def create_and_upload() -> dict:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'backup_{timestamp}.sql'
        filepath = f'/tmp/{filename}'

        db = settings.DATABASES['default']
        env = os.environ.copy()
        env['PGPASSWORD'] = db.get('PASSWORD', '')

        cmd = [
            'pg_dump',
            '-h', db.get('HOST', 'localhost'),
            '-U', db.get('USER', 'postgres'),
            '-d', db.get('NAME', 'forex_erp'),
            '-f', filepath,
            '--no-password',
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'pg_dump error: {result.stderr}')

        s3_key = f'backups/{filename}'
        if settings.AWS_ACCESS_KEY_ID:
            s3 = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            s3.upload_file(filepath, settings.AWS_STORAGE_BUCKET_NAME, s3_key)
            os.remove(filepath)
            return {'status': 'ok', 'file': s3_key, 'storage': 's3'}

        return {'status': 'ok', 'file': filepath, 'storage': 'local'}
