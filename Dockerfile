FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 INVOICEFLOW_DATA=/app/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[postgres,kafka]"
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app
USER app
EXPOSE 8000
CMD ["invoiceflow", "serve", "--port", "8000"]
