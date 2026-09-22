FROM python:3.12-slim

WORKDIR /opt/pd-proxy

# Build-зависимости для llama-cpp-python (компиляция C++)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ cmake curl && \
    rm -rf /var/lib/apt/lists/*

# Зависимости — отдельный слой для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY app/ app/
COPY config/ config/
COPY static/ static/
COPY gunicorn.conf.py .

# Каталог для кэша модели FastJev (volume mount)
RUN mkdir -p /opt/pd-proxy/models
ENV HF_HOME=/opt/pd-proxy/models

# Non-root user
RUN useradd -r -s /bin/false pdproxy && chown -R pdproxy:pdproxy /opt/pd-proxy
USER pdproxy

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1

# Production: gunicorn + uvicorn workers
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
