# ---------- Stage 1: build the React frontend ----------
FROM node:22-slim AS frontend

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# A stale tsbuildinfo makes `tsc -b` think it is up to date and skip type
# checking; remove it so the build is reproducible from a clean state.
RUN rm -f tsconfig.tsbuildinfo && npm run build


# ---------- Stage 2: Python runtime ----------
FROM python:3.11-slim

WORKDIR /app

COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

# torch is OFF by default. Measured footprint without it is ~200 MB RSS,
# which fits Render Free's 512 MB; CPU torch adds roughly 300-400 MB and
# pushes it over. With torch absent, stage 9 (ai_classification) reports
# "skipped" and the DSP classifier carries the analysis -- every other
# stage is unaffected. See rfplatform/pipeline/stages.py::_run_ml_classifier.
#
# On a host with >=1 GB RAM, build with:  --build-arg INSTALL_TORCH=true
# The CPU-only index is deliberate: the PyPI Linux torch wheel is ~527 MB
# and pulls in multi-GB nvidia-* CUDA packages.
ARG INSTALL_TORCH=false
RUN if [ "$INSTALL_TORCH" = "true" ]; then \
      pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0 \
      || pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch; \
    fi

COPY rfplatform ./rfplatform
COPY --from=frontend /build/dist ./static

# Every writable path the app uses lives under /tmp: uploads
# (rfplatform/api/main.py) and the sqlite history db (rfplatform/storage/db.py).
# That suits hosts with a read-only or ephemeral image filesystem.
ENV PYTHONUNBUFFERED=1 \
    RFPLATFORM_STATIC_DIR=/app/static

EXPOSE 10000

# Bind to $PORT, never a hardcoded port. The previous Dockerfile hardcoded
# 8000, which is why Render reported "no open ports detected" and the
# service never went live.
CMD ["sh", "-c", "uvicorn rfplatform.api.server:app --host 0.0.0.0 --port ${PORT:-10000}"]
