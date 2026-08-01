# Cloud Run deployment image for the FastAPI backend.
#
# Built from the repo root (not backend/) because the app reads
# data/catalog/vehicles.csv at runtime for the in-memory vehicle catalog —
# a sibling directory to backend/, so both must be in the build context.
#
# Not used by Render, which builds backend/ directly via buildpacks and
# ignores this file.
FROM python:3.11-slim

WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
COPY data data

WORKDIR /app/backend
RUN pip install --no-cache-dir -e .

ENV PORT=8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
