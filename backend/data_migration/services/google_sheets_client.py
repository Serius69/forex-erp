# data_migration/services/google_sheets_client.py
"""
Cliente para Google Sheets API v4.
Usa service account credentials (JSON key file).
No requiere OAuth interactivo — funciona en entornos server.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Scopes requeridos ──────────────────────────────────────────────────────────
SCOPES_READ = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
]
SCOPES_WRITE = [
    'https://www.googleapis.com/auth/spreadsheets',   # read + write
    'https://www.googleapis.com/auth/drive',
]
# Legacy alias
SCOPES = SCOPES_READ

SHEETS_BASE = 'https://sheets.googleapis.com/v4/spreadsheets'


def _get_credentials_path() -> Path:
    path = Path(getattr(settings, 'GOOGLE_SHEETS_CREDENTIALS_PATH', ''))
    if not path.exists():
        raise FileNotFoundError(
            f'Google Sheets credentials not found at: {path}. '
            'Set GOOGLE_SHEETS_CREDENTIALS_PATH in settings.'
        )
    return path


def _get_access_token(writable: bool = False) -> str:
    """
    Obtiene un access token usando JWT + service account.
    writable=True solicita scopes de escritura para push_snapshot.
    """
    scopes = SCOPES_WRITE if writable else SCOPES_READ

    creds_path = _get_credentials_path()
    with open(creds_path) as f:
        creds = json.load(f)

    # Si existe google-auth, usarla (más robusta)
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests as google_requests

        credentials = service_account.Credentials.from_service_account_file(
            str(creds_path), scopes=scopes
        )
        request = google_requests.Request()
        credentials.refresh(request)
        return credentials.token

    except ImportError:
        # Fallback: JWT manual con RS256
        creds['_scopes'] = scopes
        return _jwt_access_token(creds)


def _jwt_access_token(creds: dict) -> str:
    """Genera un access token via JWT RS256 usando solo stdlib + requests."""
    import time
    import base64
    import json as json_mod

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        raise ImportError(
            'Instala cryptography o google-auth: pip install cryptography google-auth'
        )

    now = int(time.time())
    scopes = creds.pop('_scopes', SCOPES_READ)
    claim = {
        'iss': creds['client_email'],
        'scope': ' '.join(scopes),
        'aud': 'https://oauth2.googleapis.com/token',
        'iat': now,
        'exp': now + 3600,
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

    header = b64url(json_mod.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
    payload = b64url(json_mod.dumps(claim).encode())
    signing_input = f'{header}.{payload}'.encode()

    private_key = serialization.load_pem_private_key(
        creds['private_key'].encode(), password=None, backend=default_backend()
    )
    signature = b64url(private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256()))

    jwt_token = f'{header}.{payload}.{signature}'

    resp = requests.post(
        'https://oauth2.googleapis.com/token',
        data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': jwt_token},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()['access_token']


class GoogleSheetsClient:
    """
    Cliente de lectura/escritura para Google Sheets API v4.

    Uso lectura:
        client = GoogleSheetsClient('1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms')
        meta   = client.get_spreadsheet_metadata()
        rows   = client.get_all_rows('Hoja1')

    Uso escritura (requiere GOOGLE_SHEETS_WRITABLE=True en settings):
        client = GoogleSheetsClient('1BxiMVs0...', writable=True)
        client.ensure_sheet_tab('Kapitalya_Snapshot')
        client.clear_sheet('Kapitalya_Snapshot')
        client.write_values('Kapitalya_Snapshot', 'A1', [['col1', 'col2'], ['val1', 'val2']])
    """

    def __init__(self, spreadsheet_id: str, writable: bool = False):
        self.spreadsheet_id = spreadsheet_id
        self._writable = writable
        self._token: str | None = None

    def _headers(self) -> dict:
        if not self._token:
            self._token = _get_access_token(writable=self._writable)
        return {
            'Authorization': f'Bearer {self._token}',
            'Accept':        'application/json',
            'Content-Type':  'application/json',
        }

    def _get(self, url: str, params: dict | None = None) -> dict:
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        if resp.status_code == 401:
            self._token = _get_access_token(writable=self._writable)
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, body: dict, params: dict | None = None) -> dict:
        resp = requests.post(url, headers=self._headers(), json=body, params=params, timeout=30)
        if resp.status_code == 401:
            self._token = _get_access_token(writable=self._writable)
            resp = requests.post(url, headers=self._headers(), json=body, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _put(self, url: str, body: dict, params: dict | None = None) -> dict:
        resp = requests.put(url, headers=self._headers(), json=body, params=params, timeout=30)
        if resp.status_code == 401:
            self._token = _get_access_token(writable=self._writable)
            resp = requests.put(url, headers=self._headers(), json=body, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_spreadsheet_metadata(self) -> dict:
        """Retorna metadata del spreadsheet (título, hojas, etc.)."""
        data = self._get(f'{SHEETS_BASE}/{self.spreadsheet_id}')
        return {
            'title': data.get('properties', {}).get('title'),
            'sheets': [
                {
                    'name':       s['properties']['title'],
                    'sheet_id':   s['properties']['sheetId'],
                    'row_count':  s['properties']['gridProperties'].get('rowCount', 0),
                    'col_count':  s['properties']['gridProperties'].get('columnCount', 0),
                }
                for s in data.get('sheets', [])
            ],
        }

    def get_header_row(self, sheet_name: str) -> list[str]:
        """Retorna la primera fila del sheet como lista de strings."""
        range_notation = f"'{sheet_name}'!1:1"
        data = self._get(
            f'{SHEETS_BASE}/{self.spreadsheet_id}/values/{requests.utils.quote(range_notation)}',
        )
        values = data.get('values', [[]])
        return [str(cell).strip() for cell in (values[0] if values else [])]

    def get_all_rows(self, sheet_name: str, skip_header: bool = True) -> list[list[Any]]:
        """Descarga todas las filas del sheet. Para sheets pequeños (<5k filas)."""
        range_notation = f"'{sheet_name}'"
        data = self._get(
            f'{SHEETS_BASE}/{self.spreadsheet_id}/values/{requests.utils.quote(range_notation)}',
            params={'valueRenderOption': 'UNFORMATTED_VALUE', 'dateTimeRenderOption': 'FORMATTED_STRING'},
        )
        rows = data.get('values', [])
        if skip_header and rows:
            rows = rows[1:]
        return rows

    def get_rows_batch(
        self,
        sheet_name: str,
        start_row: int,
        batch_size: int,
        header_offset: int = 1,
    ) -> list[list[Any]]:
        """
        Lee un batch de filas usando notación A1.
        start_row es 0-based (sin contar header).
        """
        # Google Sheets es 1-based; +1 para header, +1 porque las filas comienzan en 1
        first = start_row + header_offset + 1
        last  = first + batch_size - 1
        range_notation = f"'{sheet_name}'!A{first}:ZZ{last}"
        data = self._get(
            f'{SHEETS_BASE}/{self.spreadsheet_id}/values/{requests.utils.quote(range_notation)}',
            params={'valueRenderOption': 'UNFORMATTED_VALUE', 'dateTimeRenderOption': 'FORMATTED_STRING'},
        )
        return data.get('values', [])

    def get_row_count(self, sheet_name: str) -> int:
        """Cuenta filas con datos (excluyendo header)."""
        meta = self.get_spreadsheet_metadata()
        for sheet in meta['sheets']:
            if sheet['name'] == sheet_name:
                # Esto es el máximo del grid, no filas con datos
                # Hacemos un values para obtener el conteo real
                rows = self.get_all_rows(sheet_name, skip_header=True)
                return len(rows)
        raise ValueError(f"Sheet '{sheet_name}' no encontrado en spreadsheet {self.spreadsheet_id}")

    def list_sheets(self) -> list[str]:
        meta = self.get_spreadsheet_metadata()
        return [s['name'] for s in meta['sheets']]

    # ── Métodos de escritura ──────────────────────────────────────────────────

    def write_values(
        self,
        sheet_name: str,
        start_cell: str,
        values: list[list[Any]],
    ) -> dict:
        """
        Escribe una matriz de valores comenzando en start_cell.
        Ejemplo: write_values('Snapshot', 'A1', [['Fecha', 'Valor'], ['2024-01-01', 100]])
        Requiere writable=True en el constructor.
        """
        range_notation = requests.utils.quote(f"'{sheet_name}'!{start_cell}")
        url = f'{SHEETS_BASE}/{self.spreadsheet_id}/values/{range_notation}'
        return self._put(url, {'range': f"'{sheet_name}'!{start_cell}", 'values': values},
                         params={'valueInputOption': 'USER_ENTERED'})

    def append_rows(
        self,
        sheet_name: str,
        values: list[list[Any]],
    ) -> dict:
        """Agrega filas al final del sheet."""
        range_notation = requests.utils.quote(f"'{sheet_name}'!A1")
        url = f'{SHEETS_BASE}/{self.spreadsheet_id}/values/{range_notation}:append'
        return self._post(url, {'values': values},
                          params={'valueInputOption': 'USER_ENTERED', 'insertDataOption': 'INSERT_ROWS'})

    def clear_sheet(self, sheet_name: str) -> dict:
        """Limpia todos los datos del sheet (mantiene formato)."""
        range_notation = requests.utils.quote(f"'{sheet_name}'")
        url = f'{SHEETS_BASE}/{self.spreadsheet_id}/values/{range_notation}:clear'
        return self._post(url, {})

    def ensure_sheet_tab(self, title: str) -> int:
        """
        Crea la pestaña si no existe. Retorna el sheetId.
        No falla si la pestaña ya existe.
        """
        meta = self.get_spreadsheet_metadata()
        for sheet in meta['sheets']:
            if sheet['name'] == title:
                return sheet['sheet_id']

        # Crear nueva pestaña
        url = f'{SHEETS_BASE}/{self.spreadsheet_id}:batchUpdate'
        body = {'requests': [{'addSheet': {'properties': {'title': title}}}]}
        resp = self._post(url, body)
        return resp['replies'][0]['addSheet']['properties']['sheetId']
