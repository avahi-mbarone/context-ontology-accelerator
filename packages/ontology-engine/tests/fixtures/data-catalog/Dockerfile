# Build context must be the repo root:
#   docker build -f packages/context-manager/Dockerfile .
# Pin to digest to prevent supply-chain attacks via tag mutation.
# python:3.12-slim built 2026-05-19 — includes glibc deb13u3, systemd/sed/libcap2 deb13u1 CVE fixes.
FROM --platform=linux/amd64 public.ecr.aws/docker/library/python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root user for defense-in-depth, even in test fixtures.
RUN adduser --disabled-password --no-create-home --gecos "" appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
