# Kapitalya ERP — Lógica de Negocio

Este documento explica cómo funciona el negocio de casa de cambio y cómo el sistema lo refleja. Está escrito para ser entendible tanto por desarrolladores como por personas de negocio.

---

## ¿Qué hace una casa de cambio?

Una casa de cambio **compra y vende divisas** (dólares, euros, pesos argentinos, etc.) a clientes, obteniendo ganancia por la diferencia entre el precio de compra y el precio de venta. A esta diferencia se le llama **spread**.

**Ejemplo:**
- Tasa oficial BCB: **6.96 BOB por 1 USD**
- La casa compra USD al cliente a: **6.90 BOB** (cliente entrega USD, recibe BOB)
- La casa vende USD al cliente a: **7.01 BOB** (cliente entrega BOB, recibe USD)
- Spread = 7.01 - 6.90 = **0.11 BOB por dólar**
- Si se cambiaron 1,000 USD → ganancia = **110 BOB**

---

## 1. Tipos de transacción

### BUY (Compra de divisa)
La casa **compra** divisa extranjera al cliente.

```
Cliente entrega: 1,000 USD  (currency_from = USD, amount_from = 1000)
Casa entrega:    6,900 BOB  (currency_to = BOB,   amount_to = 6900)
Tasa aplicada:   6.9000     (exchange_rate = 6.9000)
```

- El inventario de USD **aumenta** (+1,000 USD)
- La caja de BOB **disminuye** (se entregaron 6,900 BOB al cliente)

### SELL (Venta de divisa)
La casa **vende** divisa extranjera al cliente.

```
Cliente entrega: 7,010 BOB  (currency_from = BOB, amount_from = 7010)
Casa entrega:    1,000 USD  (currency_to = USD,   amount_to = 1000)
Tasa aplicada:   7.0100     (exchange_rate = 7.0100)
```

- El inventario de USD **disminuye** (−1,000 USD)
- La caja de BOB **aumenta** (se recibieron 7,010 BOB del cliente)

---

## 2. Cálculo de ganancia por spread

La ganancia real se calcula a nivel de período (día, semana, mes), comparando lo que se pagó en compras vs. lo que se recibió en ventas:

```
Ganancia USD = Total BOB recibido de ventas − Total BOB pagado en compras

Ejemplo del día:
  Compras: se compraron 5,000 USD pagando 34,500 BOB   → promedio 6.90
  Ventas:  se vendieron 3,500 USD recibiendo 24,535 BOB → promedio 7.01
  
  Ganancia = 24,535 − (34,500 × 3,500/5,000)
           = 24,535 − 24,150
           = 385 BOB de ganancia en USD ese día
```

**Implementación:** `GananciaService.ganancia_por_divisa(date_from, date_to)` en [capital/services.py](../backend/capital/services.py).

---

## 3. Inventario de divisas

### ¿Qué es el inventario?
El stock de cada divisa disponible en cada sucursal para operar.

### Costo Promedio Ponderado (WAC)
Cuando se compran divisas en momentos distintos a tasas distintas, el costo del inventario se calcula como el **promedio ponderado por cantidad**:

```
WAC nuevo = (stock_actual × WAC_actual + cantidad_nueva × tasa_nueva) 
            / (stock_actual + cantidad_nueva)

Ejemplo:
  Stock actual: 10,000 USD a costo promedio 6.90
  Nueva compra: 5,000 USD a 6.95
  
  WAC nuevo = (10,000 × 6.90 + 5,000 × 6.95) / 15,000
            = (69,000 + 34,750) / 15,000
            = 103,750 / 15,000
            = 6.9167 BOB/USD
```

### Tipos de balance
- **`physical_balance`** — Efectivo físico en bóveda
- **`digital_balance`** — Saldos en cuentas bancarias / QR
- **`total_balance`** — Suma de ambos (lo que se puede vender)

### Alertas de inventario
- **Stock bajo** (`LOW_STOCK`): cuando `total_balance ≤ reorder_point`
- **Sobrestock** (`is_overstocked`): cuando `total_balance > maximum_stock`
- **Ajuste significativo** (`SIGNIFICANT_ADJUSTMENT`): diferencia > 1% en conteo

---

## 4. Capital total

El capital es el **valor total del negocio** en un momento dado, expresado en BOB:

```
Capital = Efectivo BOB
        + Saldo QR/Digital (BOB)
        + Valor divisas (stock × TC de venta actual)
        + Valor tarjetas (stock unidades × precio venta promedio)
        − Pasivos (deudas)
```

**¿Por qué al TC de venta?** Porque ese es el valor que se recibiría si se liquidara todo el inventario hoy.

**Ejemplo:**
```
Efectivo en caja:    50,000 BOB
Saldo QR/digital:    10,000 BOB
Inventario divisas:
  - 30,000 USD × 7.01 (TC venta) = 210,300 BOB
  - 500 EUR  × 7.60 (TC venta)   =   3,800 BOB
Inventario tarjetas:
  - 200 Tigo 5 BOB × 5.50 precio = 1,100 BOB
Pasivos:                                 0 BOB

CAPITAL TOTAL = 50,000 + 10,000 + 214,100 + 1,100 - 0
              = 275,200 BOB
```

**Implementación:** `CapitalService.calcular_capital()` en [capital/services.py](../backend/capital/services.py).

### Snapshot de capital
El sistema permite **fotografiar** el capital en cualquier momento (apertura, cierre, auditoría) para tener historial y detectar discrepancias.

---

## 5. Tarjetas prepago (FIFO)

La casa compra **lotes** de tarjetas prepago (Tigo, Viva, Entel, Claro) y las vende individualmente.

### Costeo FIFO (First In, First Out)
Las tarjetas se venden en el orden en que se compraron — las más antiguas primero.

```
Ejemplo:
  Lote 1 (comprado el 01/04): 100 tarjetas Tigo 5 BOB a costo 4.20 c/u
  Lote 2 (comprado el 05/04): 200 tarjetas Tigo 5 BOB a costo 4.30 c/u

  Venta de 120 tarjetas a 5.50 c/u:
    - 100 del Lote 1 (costo: 100 × 4.20 = 420 BOB)
    - 20  del Lote 2 (costo:  20 × 4.30 =  86 BOB)
    
  Total ingresos:  120 × 5.50 = 660 BOB
  Total costo:     420 + 86   = 506 BOB
  Ganancia:        660 - 506  = 154 BOB
```

### ¿Por qué FIFO?
- Refleja correctamente el costo real de cada venta
- Es el método contable más conservador y aceptado
- Permite rastrear exactamente qué lote se vendió cuándo

**Implementación:** `tarjetas/services.py` + modelos `LoteCompra`, `VentaTarjeta`, `DetalleVentaLote`.

---

## 6. Gastos operativos

Los gastos del negocio (alquiler, sueldos, servicios, etc.) se registran en BOB con categoría y método de pago.

**Categorías disponibles:**
- Alquiler, Servicios básicos, Sueldos, Comisiones
- Publicidad, Impuestos, Suministros, Mantenimiento
- Transporte, Comisiones bancarias, Otros

**Impacto en P&G:**
```
Ganancia neta = Ganancia spreads divisas
              + Ganancia tarjetas prepago
              - Gastos operativos totales
```

---

## 7. Resumen financiero completo (P&G)

```
INGRESOS:
  + Ganancia por spread USD:    1,620 BOB
  + Ganancia por spread EUR:      340 BOB
  + Ganancia tarjetas:            400 BOB
                                ─────────
  Ganancia bruta:               2,360 BOB

GASTOS:
  - Alquiler:                   3,500 BOB
  - Sueldos:                    8,000 BOB
  - Servicios:                    350 BOB
                                ─────────
  Total gastos:                11,850 BOB

  GANANCIA NETA:               -9,490 BOB  ← pérdida del período
```

**Implementación:** `GananciaService.resumen_financiero(date_from, date_to)` en [capital/services.py](../backend/capital/services.py).

---

## 8. Predicciones de tasas

El sistema predice cómo evolucionarán las tasas de cambio en las próximas 24 horas para:

1. **Orientar al operador** sobre si conviene comprar o vender más hoy
2. **Optimizar márgenes** según la franja horaria esperada
3. **Planificar inventario** antes de picos de demanda

Las predicciones tienen:
- **Tasa predicha** (punto central)
- **Intervalo de confianza** (rango probable)
- **Tasa de compra predicha** = predicción × (1 − margen%)
- **Tasa de venta predicha** = predicción × (1 + margen%)

---

## 9. Cumplimiento regulatorio (ASFI Bolivia)

### RTE — Registro de Transacciones en Efectivo
Toda operación en efectivo ≥ **USD 1,000 equivalente** debe reportarse automáticamente a la ASFI.

El sistema genera el RTE automáticamente al completar la transacción.

### ROUE — Reporte de Operaciones Inusuales/Sospechosas
Cuando una operación presenta patrones inusuales (montos fragmentados, clientes sin relación lógica con el monto, etc.), el operador puede crear un ROUE para investigación.

### PEP — Personas Expuestas Políticamente
Clientes con cargos públicos o vínculos políticos requieren monitoreo reforzado (enhanced due diligence). El sistema registra y alerta sobre transacciones de clientes PEP.

### Libro Diario (Art. 14)
Registro diario de todas las operaciones de la sucursal. Se genera automáticamente al cierre del día.

---

## 10. Autorización de transacciones grandes

Transacciones que superan ciertos montos requieren aprobación de un **supervisor o administrador** mediante PIN:

| Moneda | Límite |
|--------|--------|
| USD | > 5,000 |
| BOB | > 35,000 (~5,000 USD) |
| Otras | Equiv. > 35,000 BOB |

El PIN del supervisor está **hasheado** (bcrypt) en la base de datos — nunca se almacena en texto plano.
