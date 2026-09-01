# Hugging Face Space image for cad2pdf.
#
# This Dockerfile pulls the application straight from GitHub, so a Space
# only needs TWO files: this one and README.md. Nothing else to upload.
#
# To point it at your own fork/branch, edit REPO_URL / REPO_BRANCH below.

# ---------------------------------------------------------------------------
# Stage 1: build LibreDWG's dwg2dxf, which provides .dwg support.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS dwg-builder

ARG LIBREDWG_VERSION=0.13.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --disable-werror is required: LibreDWG builds with -Werror and newer GCC
# raises -Walloc-size on its own allocation macros, which fails the build.
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
# Stage 2: the app, cloned from GitHub.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ARG REPO_URL=https://github.com/fishewb-del/CAD2PDF.git
ARG REPO_BRANCH=claude/cad-to-pdf-converter-y9kc7s

# HOME and MPLCONFIGDIR must be writable for the non-root Space user.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dwg-builder /usr/local/bin/dwg2dxf /usr/local/bin/dwg2dxf

WORKDIR /app
RUN git clone --depth 1 --branch "${REPO_BRANCH}" "${REPO_URL}" . \
    && pip install --no-cache-dir -r requirements.txt

# Hugging Face runs Spaces as a non-root user.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Must match `app_port` in the Space's README.md frontmatter.
EXPOSE 8000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "4", "--timeout", "180"]
