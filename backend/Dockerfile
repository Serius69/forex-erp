# backend/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    curl \
    wget \
    git \
    # Playwright / Chromium
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    # Prophet / scipy / numpy
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Prophet: el wheel trae un bundle cmdstan-2.33.1 INCOMPLETO (sin makefile) que rompe
# el backend CmdStanPy ('Prophet' object has no attribute 'stan_backend'). Compilamos
# el CmdStan real en la ruta que Prophet exige para que el forecaster Prophet funcione.
RUN python -c "import cmdstanpy, prophet, pathlib; \
    d = str(pathlib.Path(prophet.__file__).parent / 'stan_model'); \
    cmdstanpy.install_cmdstan(version='2.33.1', dir=d, overwrite=True, cores=4, progress=False)"

RUN python -m playwright install chromium --with-deps 2>/dev/null || \
    echo "Playwright install skipped"

COPY . .

RUN mkdir -p staticfiles media ml-models logs

EXPOSE 8007 8008

CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8007", "--workers", "4"]
