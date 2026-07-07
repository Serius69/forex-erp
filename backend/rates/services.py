import requests
from bs4 import BeautifulSoup
from decimal import Decimal
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import logging
from .models import Currency, ExchangeRate, RateConfiguration
from core.finance import quantize_rate, quantize_money, RATE_Q, MONEY_Q

logger = logging.getLogger(__name__)

class RateService:
    """Servicio para gestión de tasas de cambio"""
    
    def __init__(self):
        self.sources = {
            'BCB': {
                'url': 'https://www.bcb.gob.bo/',
                'parser': self._parse_bcb_rates
            },
            'BCP': {
                'url': 'https://www.bcp.com.bo/librerias/indicadores/tipo_cambio.php',
                'parser': self._parse_bcp_rates
            }
        }
    
    def fetch_official_rates(self, source='BCB'):
        """Obtiene tasas oficiales de la fuente especificada"""
        try:
            source_config = self.sources.get(source)
            if not source_config:
                raise ValueError(f"Fuente {source} no configurada")
            
            response = requests.get(
                source_config['url'],
                timeout=10,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            response.raise_for_status()
            
            rates = source_config['parser'](response.content)
            
            # Guardar en base de datos
            for currency_code, rate_value in rates.items():
                self._save_rate(currency_code, rate_value, source)
            
            return rates
            
        except Exception as e:
            logger.error("RATE_FETCH_FAILED source=%s error=%s", source, e)
            try:
                from core.alerts import SystemAlert
                SystemAlert.create(
                    component='rates',
                    message=f'Fallo al obtener tasas de {source}: {type(e).__name__}',
                    severity='HIGH',
                    details={'source': source, 'error': str(e)},
                )
            except Exception:
                pass
            return self._get_fallback_rates()
    
    def _parse_bcb_rates(self, content):
        """
        Parser específico para BCB — extrae tasas del HTML oficial.

        COMPLIANCE: Si la tabla no se encuentra o no contiene datos válidos,
        retorna un diccionario vacío y registra el evento.
        NO se usan valores hardcodeados como fallback aquí.
        El fallback con INFERENCE está en BCBOfficialFetcher._hardcoded_fallback().
        """
        soup  = BeautifulSoup(content, 'html.parser')
        rates = {}

        # Buscar tabla de cotizaciones (múltiples selectores por robustez)
        rate_table = (
            soup.find('table', {'class': 'cotizaciones'}) or
            soup.find('table', class_=lambda c: c and 'tipo' in c.lower())
        )
        if rate_table:
            rows = rate_table.find_all('tr')[1:]  # saltar header
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    currency = cols[0].text.strip()
                    rate_str = cols[2].text.strip().replace(',', '.')
                    try:
                        rate_val = Decimal(rate_str)
                        if currency == 'DÓLAR ESTADOUNIDENSE':
                            rates['USD'] = rate_val
                        elif currency == 'EURO':
                            rates['EUR'] = rate_val
                        elif currency in ('REAL BRASILEÑO', 'REAL BRASILENO'):
                            rates['BRL'] = rate_val
                        elif currency == 'PESO ARGENTINO':
                            rates['ARS'] = rate_val
                        elif currency == 'PESO CHILENO':
                            rates['CLP'] = rate_val
                        elif currency == 'SOL PERUANO':
                            rates['PEN'] = rate_val
                    except Exception:
                        continue

        if not rates:
            logger.warning(
                "BCB_PARSE_EMPTY — no se extrajeron tasas del HTML. "
                "Retornando vacío; el fetcher BCBOfficialFetcher usará INFERENCE fallback."
            )

        return rates
    
    def _parse_bcp_rates(self, content):
        """Parser específico para BCP"""
        # Implementar según estructura del sitio
        return {}
    
    def _save_rate(self, currency_code, rate_value, source, source_method='SCRAP',
                   source_url=None, created_by=None):
        """
        Guarda la tasa en la base de datos con cuantización financiera y trazabilidad.

        - official_rate se almacena como rate BCB por UNIDAD (invariante).
        - buy_rate/sell_rate se calculan por scale_factor unidades.
        - source_method debe ser 'API', 'SCRAP', 'MANUAL' o 'INFERENCE'.
        - created_by debe pasarse cuando el origen es MANUAL (admin).
        """
        try:
            currency_from = Currency.objects.get(code=currency_code)
            currency_to   = Currency.objects.get(code='BOB')
            now           = timezone.now()

            # Cerrar tasas anteriores (mismo market_type=official)
            ExchangeRate.objects.filter(
                currency_from=currency_from,
                currency_to=currency_to,
                market_type='official',
                valid_until__isnull=True,
            ).update(valid_until=now)

            config             = self._get_rate_configuration(currency_from, currency_to)
            buy_margin, sell_margin = config.get_current_margins()

            official = quantize_rate(rate_value)  # per-unit BCB rate (stored as-is)

            scale            = Decimal(str(currency_from.scale_factor))
            official_scaled  = official * scale
            buy_rate         = quantize_rate(official_scaled * (Decimal('1') - buy_margin  / Decimal('100')))
            sell_rate        = quantize_rate(official_scaled * (Decimal('1') + sell_margin / Decimal('100')))

            ExchangeRate.objects.create(
                currency_from=currency_from,
                currency_to=currency_to,
                official_rate=official,
                buy_rate=buy_rate,
                sell_rate=sell_rate,
                market_type='official',
                source=source,
                valid_from=now,
                # ── Trazabilidad ──────────────────────────────────────────────
                source_method=source_method,
                source_url=source_url,
                fetched_at=now,
                created_by=created_by,
                is_validated=(source_method == 'MANUAL'),  # manual = pre-validated
                confidence=Decimal('0.95') if source_method in ('API', 'SCRAP') else Decimal('0.500'),
            )
        except Currency.DoesNotExist:
            logger.warning("Divisa %s no encontrada en base de datos", currency_code)
        except Exception as e:
            logger.error("Error guardando tasa para %s: %s", currency_code, e, exc_info=True)

    def _get_rate_configuration(self, currency_from, currency_to):
        """Obtiene o crea configuración de tasa con márgenes por defecto."""
        config, _ = RateConfiguration.objects.get_or_create(
            currency_from=currency_from,
            currency_to=currency_to,
            defaults={
                'buy_margin_morning':    Decimal('0.30'),
                'sell_margin_morning':   Decimal('0.30'),
                'buy_margin_afternoon':  Decimal('0.25'),
                'sell_margin_afternoon': Decimal('0.25'),
                'buy_margin_evening':    Decimal('0.35'),
                'sell_margin_evening':   Decimal('0.35'),
            }
        )
        return config
   
    def _get_fallback_rates(self):
        """Obtiene las últimas tasas conocidas como fallback."""
        rates = {}
        currencies = ['USD', 'EUR', 'BRL', 'ARS']

        for currency_code in currencies:
            try:
                currency    = Currency.objects.get(code=currency_code)
                latest_rate = ExchangeRate.objects.filter(
                    currency_from=currency,
                    currency_to__code='BOB',
                ).first()
                if latest_rate:
                    rates[currency_code] = latest_rate.official_rate
            except Exception:
                pass

        return rates
   
    def get_current_rates(self, currency_from_code, currency_to_code='BOB'):
       """Obtiene las tasas actuales con cache"""
       cache_key = f"rate_{currency_from_code}_{currency_to_code}"
       cached_rates = cache.get(cache_key)
       
       if cached_rates:
           return cached_rates
       
       try:
           currency_from = Currency.objects.get(code=currency_from_code)
           currency_to = Currency.objects.get(code=currency_to_code)
           
           rate = ExchangeRate.objects.filter(
               currency_from=currency_from,
               currency_to=currency_to,
               valid_until__isnull=True
           ).first()
           
           if rate:
                scale = rate.currency_from.scale_factor
                rates_data = {
                    # buy/sell son por scale_factor unidades (ej. por 1000 CLP)
                    'official':           str(quantize_rate(rate.official_rate)),
                    'buy':                str(quantize_rate(rate.buy_rate)),
                    'sell':               str(quantize_rate(rate.sell_rate)),
                    'spread':             str(quantize_rate(rate.spread)),
                    'spread_percentage':  str(rate.spread_percentage),
                    # Metadatos de escala — el frontend los usa para display correcto
                    'scale_factor':       scale,
                    'market_type':        rate.market_type,
                    'last_update':        rate.updated_at.isoformat(),
                    'rate_id':            rate.id,
                }
                # Cache por 2 minutos — tasas de divisas cambian con frecuencia
                cache.set(cache_key, rates_data, 120)
                return rates_data
               
       except Currency.DoesNotExist:
           logger.error(f"Divisa no encontrada: {currency_from_code} o {currency_to_code}")
       
       return None
   
    def calculate_exchange(self, amount: Decimal, currency_from_code: str,
                           currency_to_code: str, transaction_type: str) -> dict:
        """
        Calcula el monto resultante de un intercambio.

        UNIDADES: `amount` está en unidades del sistema (1 unidad = scale_factor
        unidades reales para CLP/ARS). La tasa buy/sell ya está expresada en el
        mismo escalado, por lo que la multiplicación directa es correcta.

        Perspectiva de la CASA DE CAMBIOS:
          BUY  → casa compra divisa extranjera del cliente → usa buy_rate
                  cliente recibe BOB: amount_to = amount_from * buy_rate
          SELL → casa vende divisa extranjera al cliente   → usa sell_rate
                  cliente entrega BOB: amount_to = amount_from * sell_rate
        """
        rates = self.get_current_rates(currency_from_code, currency_to_code)
        if not rates:
            raise ValueError(f"Tasas no disponibles para {currency_from_code}/{currency_to_code}")

        amount = quantize_rate(amount)  # 4dp para precisión en divisas
        scale  = int(rates.get('scale_factor', 1))

        if transaction_type == 'BUY':
            rate   = Decimal(rates['buy'])
            result = quantize_money(amount * rate)
        else:
            rate   = Decimal(rates['sell'])
            if rate == 0:
                raise ValueError("Tasa de venta no puede ser cero")
            result = quantize_money(amount * rate)

        return {
            'amount_from':       str(amount),
            'amount_to':         str(result),
            'rate':              str(quantize_rate(rate)),
            'scale_factor':      scale,
            'transaction_type':  transaction_type,
            'currency_from':     currency_from_code,
            'currency_to':       currency_to_code,
        }