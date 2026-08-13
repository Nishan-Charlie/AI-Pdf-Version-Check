# Fire Safety Regulation Comparison — Python service
#
# Pinned base and pinned dependencies, so the image is the same on every
# machine. That is the point of running this in a container: the comparison
# service stops depending on which Python, which PyTorch, and which Windows
# privileges a particular laptop happens to have.

FROM python:3.12-slim AS base

# Unbuffered so uvicorn's output reaches `docker logs` as it happens rather
# than in blocks; no .pyc files to write into a read-only layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# CPU-only PyTorch, installed before everything else so it is its own layer.
# The default wheel bundles CUDA libraries this project never uses and that
# alone is about 2 GB of image.
RUN pip install --no-cache-dir \
        torch==2.6.0 \
        --index-url https://download.pytorch.org/whl/cpu

# Dependencies before source, so editing code does not reinstall them.
COPY requirements-lock.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY config.py ./
COPY api/ ./api/
COPY comparison/ ./comparison/
COPY database/ ./database/
COPY ingestion/ ./ingestion/
COPY corpus/*.py ./corpus/
COPY evaluation/ ./evaluation/
COPY scripts/ ./scripts/

# Model weights live here, mounted as a named volume by compose. Without it,
# every container start re-downloads the encoder.
ENV HF_HOME=/models

# The corpus and the database are volumes too; create the mount points so they
# exist even when nothing is mounted over them.
RUN mkdir -p /models /app/corpus/raw /app/corpus/text

# Run as a non-root user, but make the mounted paths writable by it.
RUN useradd --create-home --uid 10001 app \
 && chown -R app:app /models /app
USER app

EXPOSE 8000

# Reports unhealthy until the service answers, which is what compose waits on
# before starting the dashboard.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4).status==200 else 1)"

# No --reload: it runs a second process and restarts the worker mid-request,
# which shows up in the dashboard as `socket hang up`.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
