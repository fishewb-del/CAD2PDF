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
    && make -j2 \
    && cp programs/dwg2dxf /usr/local/bin/dwg2dxf \
    && strip /usr/local/bin/dwg2dxf

# ---------------------------------------------------------------------------
# Stage 2: the actual app image.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/home/appuser/.matplotlib

WORKDIR /app

COPY --from=dwg-builder /usr/local/bin/dwg2dxf /usr/local/bin/dwg2dxf

# Fonts. python:3.11-slim ships none at all, and ezdxf needs a real TrueType
# font to draw TEXT, MTEXT, dimensions and block attributes - without one,
# any drawing containing text fails with "no fonts available, not even
# fallback fonts". Liberation is the important one: it is metric-compatible
# with Arial, Helvetica, Times New Roman and Courier New, which is what CAD
# text styles overwhelmingly ask for, so text lands at the width the drawing
# expects. DejaVu covers everything else. Together about 10 MB.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user; conversions only ever touch per-request temp dirs.
RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R appuser:appuser /app /home/appuser

USER appuser

# Build matplotlib's font cache now, at image build time. Otherwise the
# first request after every cold start pays for it - and on Render's free
# plan the instance sleeps when idle, so "cold start" means most mornings.
RUN python -c "import matplotlib.pyplot" \
    && python -c "from cad2pdf.fontsetup import ensure_fonts, font_count; \
                  ensure_fonts(); print('fonts available:', font_count())"

EXPOSE 8000

# Worker/thread counts and timeouts come from the environment so the same
# image runs on a 512 MB free instance (1 worker) and on a larger paid one
# without a rebuild. See render.yaml for the free-tier values.
CMD ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-1} --threads ${WEB_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-120} --graceful-timeout 30 --access-logfile - --error-logfile -"]
