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

# Pull the FastEmbed ONNX weights at build time.
#
# Without this the first request downloads them instead, and on Cloud Run
# that download fails outright — "Could not load model ... from any source"
# after ~39 seconds of retrying, on every single request, with retrieval
# silently degraded to nothing. Baking them makes the image large and the
# build slow, which is the correct trade: it is paid once per deploy rather
# than by every customer waiting for a reply.
#
# FASTEMBED_CACHE_PATH is set for both this layer and the runtime so the
# weights are looked up where they were written, rather than under a home
# directory that differs between build and run.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN python -c "\
from fastembed import TextEmbedding, SparseTextEmbedding; \
from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'); \
SparseTextEmbedding(model_name='Qdrant/bm25'); \
TextCrossEncoder(model_name='Xenova/ms-marco-MiniLM-L-6-v2'); \
print('embedding models cached')"

ENV PORT=8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
