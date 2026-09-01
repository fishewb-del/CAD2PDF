# ---------------------------------------------------------------------------
# Stage 1: build LibreDWG's dwg2dxf, which gives us native .dwg support.
# DWG is Autodesk's closed format; LibreDWG is the free reader for it.
# It isn't packaged for Ubuntu/Debian slim, so we build just the one tool.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS dwg-builder

ARG LIBREDWG_VERSION=0.13.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --disable-werror is required: LibreDWG builds with -Werror, and newer GCC
# (Debian bookworm's) raises -Walloc-size on its own object-allocation
# macros, which would otherwise fail the build.

WORKDIR /build
RUN curl -sSL -o libredwg.tar.gz \
        "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.gz" \
    && tar xzf libredwg.tar.gz \
    && cd "libredwg-${LIBREDWG_VERSION}" \
    && ./configure --disable-python --disable-bindings \
                   --disable-shared --enable-static \
                   --disable-werror \
    && make -j"$(nproc)" \
    && cp programs/dwg2dxf /usr/local/bin/dwg2dxf \
    && strip /usr/local/bin/dwg2dxf

# ---------------------------------------------------------------------------
# Stage 2: the actual app image.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

COPY --from=dwg-builder /usr/local/bin/dwg2dxf /usr/local/bin/dwg2dxf

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user; conversions only ever touch per-request temp dirs.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 180"]
