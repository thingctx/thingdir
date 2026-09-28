# A thingdir TDD for a scale to zero container host (Azure Container Apps, Cloud
# Run, Cloudflare Containers): object store plus TD validation, SPARQL off.
# The host sets PORT; the rest is read from the environment by the CLI:
#   THINGDIR_STORE          an fsspec URL, e.g. az://things (Azure Blob) or s3://
#   THINGDIR_WRITE_TOKEN    require a bearer token on POST/PUT/DELETE
#   THINGDIR_DEFAULT_TTL    seconds applied to a registration with no ttl
#   THINGDIR_MAX_TTL        upper bound clamped onto any requested ttl
#   THINGDIR_READ_CACHE     seconds of Cache-Control on reads (CDN serves them)
# Azure Blob credentials for adlfs come from the environment too:
#   AZURE_STORAGE_ACCOUNT_NAME, AZURE_STORAGE_ACCOUNT_KEY (or a connection string)
#
# Almost free profile: leave THINGDIR_SWEEP_INTERVAL unset and do not enable
# SPARQL, so no background loop keeps the instance warm and it scales to zero.
# Set THINGDIR_READ_CACHE so the CDN absorbs reads, and reclaim expired entries
# with an external scheduler calling POST /admin/prune (lazy expiry hides them
# meanwhile).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app
COPY . /app

# server pulls the HTTP stack (it is not in the base install); azure pulls
# adlfs for Azure Blob; validate pulls thingctx for write checks.
# Swap azure for s3 (R2) or postgres (SqlStore) if you change the store.
RUN pip install ".[server,azure,validate]"

EXPOSE 8080

# The CLI reads PORT and THINGDIR_* from the environment, so no args are needed.
CMD ["thingdir"]
