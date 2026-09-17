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

# CPU-only torch (~200 MB) from PyTorch's index instead of the PyPI wheel
# (~527 MB + multi-GB nvidia-* CUDA deps). The fallback covers the case
# where this exact version has not been published to the CPU index.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0 \
 || pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY rfplatform ./rfplatform
COPY --from=frontend /build/dist ./static

# Every writable path the app uses lives under /tmp: uploads
# (rfplatform/api/main.py) and the sqlite history db (rfplatform/storage/db.py).
# That keeps the image itself read-only, which is what Hugging Face Spaces,
# Render and Fly all expect.
ENV PYTHONUNBUFFERED=1 \
    RFPLATFORM_STATIC_DIR=/app/static \
    PORT=7860

EXPOSE 7860

# Bind to $PORT, never a hardcoded port -- Render/Fly inject their own and a
# hardcoded port is why the previous deploy reported "no open ports detected".
CMD ["sh", "-c", "uvicorn rfplatform.api.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
