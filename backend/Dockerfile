# Pinned to a version and its digest (the multi-arch index), not the floating
# `3.11-slim`: a tag that is pulled once sits wherever it was that day. To
# move it, change this one line. The weekly audit compares the digest with
# what `python:3.11-slim` points at and fails when the pin falls behind; a
# move to another minor also means changing that tag in
# .github/workflows/security-audit.yml.
ARG PYTHON_IMAGE=python:3.11.17-slim-trixie@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce

# ---------------------------------------------------------------------------
# build — where anything is compiled. The compiler and the headers stay
# here: shipped in the runtime image they are what an image scanner counts
# (binutils alone was 70 of its 156 findings), and nothing runs them there.
#
# The virtualenv is created without pip on purpose. pip, setuptools and
# wheel would be copied into the runtime image with it, each a scanner
# finding of its own and none of them used at runtime; the image's own pip
# installs into the venv from outside instead.
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Optional dependency groups from pyproject.toml, comma-separated. Empty by
# default: `redis` is for deployments that run several backends and share
# the rate limiter's counters (RATE_LIMIT_STORAGE_URI).
ARG PIP_EXTRAS=""

COPY pyproject.toml ./
RUN python -m venv --without-pip /opt/venv \
    && pip --python /opt/venv/bin/python install --no-cache-dir ".${PIP_EXTRAS:+[${PIP_EXTRAS}]}"

# The same environment plus the `dev` extra, and pip inside it this time:
# a development container is where someone tries a package out.
FROM build AS build-dev
RUN /opt/venv/bin/python -m ensurepip --default-pip \
    && /opt/venv/bin/pip install --no-cache-dir ".[dev]"

# ---------------------------------------------------------------------------
# runtime-files — the filesystem both targets below run on, before it is
# flattened.
#
# System packages are the ones something calls: `psql` (the entrypoint) and
# `pg_dump` (a module's backup before its tables are dropped), and Pango
# with HarfBuzz for WeasyPrint. Cairo, GDK-PixBuf and shared-mime-info
# were WeasyPrint's requirements before version 53 and are no longer
# loaded; with them went libtiff and Debian's libxml2.
#
# The Python image ships pip, setuptools and wheel in its own
# site-packages. The application runs from /opt/venv and never calls them,
# so they go — an image scanner counts them, two of its high findings.
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime-files

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip uninstall -y pip setuptools wheel

# Non-root user, owning /app and the directories a volume mounts on:
# storage for patient files, and /var/log/dienteazul for the server-error
# log the control panel reads (ADR 0060). The app runs as appuser and
# /var/log is root's, so the directory has to exist and be given away
# here — created at runtime it would fail, and the panel would have
# nothing to show.
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/storage /var/log/dienteazul \
    && chown appuser:appuser /app /app/storage /var/log/dienteazul

# ---------------------------------------------------------------------------
# runtime — the same filesystem as one layer.
#
# Uninstalling above is not enough by itself: the files stay in the base
# image's layer, and a scanner reads layers (measured on the PostgreSQL
# image, where a binary removed in a layer on top went on being counted).
# Copying the filesystem into an empty image leaves no layer that ever held
# them. Only this base is flattened — the virtualenv and the code are
# layers of their own on top, so a code change still rebuilds and ships
# only the code.
#
# The copy drops the image's metadata; what matters of it is declared
# again here. LANG is the Python image's own, and is what makes the
# interpreter's default encoding UTF-8.
# ---------------------------------------------------------------------------
FROM scratch AS runtime

COPY --from=runtime-files / /

ENV PATH=/opt/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8

WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

# ---------------------------------------------------------------------------
# dev — runtime image plus the test toolchain (pytest, ruff) from the
# `dev` extra. docker-compose.yml builds this target, so
# `docker-compose exec backend python -m pytest` works out of the box
# instead of needing a manual pip install after every container recreate.
#
# Declared BEFORE `prod` on purpose: a build with no --target uses the last
# stage, and docker-compose.coolify.yml builds without one. Keeping `prod`
# last is what stops the test toolchain from shipping to production.
# ---------------------------------------------------------------------------
FROM runtime AS dev
# Owned by appuser here, unlike in prod: a virtualenv has no per-user site,
# so a root-owned one would leave `pip install` in the container nowhere to
# write.
COPY --from=build-dev --chown=appuser:appuser /opt/venv /opt/venv
COPY --chown=appuser:appuser . .
RUN chmod +x /app/docker-entrypoint.sh
USER appuser

# ---------------------------------------------------------------------------
# prod — default target: the runtime image, no test toolchain. Must stay the
# last stage in this file.
# ---------------------------------------------------------------------------
FROM runtime AS prod
COPY --from=build /opt/venv /opt/venv
COPY --chown=appuser:appuser . .
RUN chmod +x /app/docker-entrypoint.sh
USER appuser
