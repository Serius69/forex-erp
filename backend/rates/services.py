import requests
from bs4 import BeautifulSoup
from decimal import Decimal
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import logging
from .models import Currency, ExchangeRate, RateConfiguration

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
            logger.error(f"Error obteniendo tasas de {source}: {str(e)}")
            return self._get_fallback_rates()
    
    def _parse_bcb_rates(self, content):
        """Parser específico para BCB"""
        soup = BeautifulSoup(content, 'html.parser')
        rates = {}
        
        # Buscar tabla de cotizaciones (adaptar según estructura real)
        rate_table = soup.find('table', {'class': 'cotizaciones'})
        if rate_table:
            rows = rate_table.find_all('tr')[1:]  # Saltar header
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    currency = cols[0].text.strip()
                    rate = cols[2].text.strip().replace(',', '.')
                    
                    if currency == 'DÓLAR ESTADOUNIDENSE':
                        rates['USD'] = Decimal(rate)
                    elif currency == 'EURO':
                        rates['EUR'] = Decimal(rate)
        
        # Si no se encuentran tasas, usar valores por defecto
        if not rates:
            rates = {
                'USD': Decimal('6.96'),
                'EUR': Decimal('7.50'),
                'BRL': Decimal('1.40'),
                'ARS': Decimal('0.0085')
            }
        
        return rates
    
    def _parse_bcp_rates(self, content):
        """Parser específico para BCP"""
        # Implementar según estructura del sitio
        return {}
    
    def _save_rate(self, currency_code, rate_value, source):
        """Guarda la tasa en la base de datos"""
        try:
            currency_from = Currency.objects.get(code=currency_code)
            currency_to = Currency.objects.get(code='BOB')
            # Cerrar tasas anteriores
            ExchangeRate.objects.filter(
                currency_from=currency_from,
                currency_to=currency_to,
                valid_until__isnull=True
            ).update(valid_until=timezone.now())
           
            # Calcular tasas comerciales
            config = self._get_rate_configuration(currency_from, currency_to)
            buy_margin, sell_margin = config.get_current_margins()
            
            buy_rate = rate_value * (Decimal('1') - buy_margin / Decimal('100'))
            sell_rate = rate_value * (Decimal('1') + sell_margin / Decimal('100'))
            
            # Crear nueva tasa
            ExchangeRate.objects.create(
                currency_from=currency_from,
                currency_to=currency_to,
                official_rate=rate_value,
                buy_rate=buy_rate,
                sell_rate=sell_rate,
                source=source,
                valid_from=timezone.now()
            )
        except Currency.DoesNotExist:
           logger.warning(f"Divisa {currency_code} no encontrada")
        except Exception as e:
           logger.error(f"Error guardando tasa para {currency_code}: {str(e)}")
   
    def _get_rate_configuration(self, currency_from, currency_to):
       """Obtiene o crea configuración de tasa"""
       config, created = RateConfiguration.objects.get_or_create(
           currency_from=currency_from,
           currency_to=currency_to,
           defaults={
               'buy_margin_morning': Decimal('0.30'),
               'sell_margin_morning': Decimal('0.30'),
               'buy_margin_afternoon': Decimal('0.25'),
               'sell_margin_afternoon': Decimal('0.25'),
               'buy_margin_evening': Decimal('0.35'),
               'sell_margin_evening': Decimal('0.35'),
           }
       )
       return config
   
    def _get_fallback_rates(self):
       """Obtiene las últimas tasas conocidas como fallback"""
       rates = {}
       currencies = ['USD', 'EUR', 'BRL', 'ARS']
       
       for currency_code in currencies:
           try:
               currency = Currency.objects.get(code=currency_code)
               latest_rate = ExchangeRate.objects.filter(
                   currency_from=currency,
                   currency_to__code='BOB'
               ).first()
               
               if latest_rate:
                   rates[currency_code] = latest_rate.official_rate
           except:
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
               rates_data = {
                   'official': float(rate.official_rate),
                   'buy': float(rate.buy_rate),
                   'sell': float(rate.sell_rate),
                   'spread': float(rate.spread),
                   'spread_percentage': float(rate.spread_percentage),
                   'last_update': rate.updated_at.isoformat()
               }
               
               # Cache por 5 minutos
               cache.set(cache_key, rates_data, 300)
               return rates_data
               
       except Currency.DoesNotExist:
           logger.error(f"Divisa no encontrada: {currency_from_code} o {currency_to_code}")
       
       return None
   
    def calculate_exchange(self, amount, currency_from_code, currency_to_code, transaction_type):
       """Calcula el monto de intercambio"""
       rates = self.get_current_rates(currency_from_code, currency_to_code)
       
       if not rates:
           raise ValueError("Tasas no disponibles")
       
       if transaction_type == 'BUY':
           # Cliente compra divisas (casa de cambio vende)
           rate = Decimal(str(rates['sell']))
           result = amount * rate
       else:
           # Cliente vende divisas (casa de cambio compra)
           rate = Decimal(str(rates['buy']))
           result = amount * rate
       
       return {
           'amount_from': amount,
           'amount_to': result,
           'rate': rate,
           'transaction_type': transaction_type
       }