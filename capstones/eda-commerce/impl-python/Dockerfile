# One image per service:  docker build --build-arg SERVICE=order_svc -t eda-commerce/order-svc-python:dev .
# The build context must be the capstone root's parent layout: contracts_py generates from ../contracts,
# so build from the capstone root with:  docker build -f impl-python/Dockerfile --build-arg SERVICE=... .
# (Not built in the authoring environment: no Docker daemon there.)
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ARG SERVICE
WORKDIR /app
COPY contracts /app/contracts
COPY impl-python /app/impl-python
WORKDIR /app/impl-python
RUN uv sync --frozen --no-dev --package "$(echo ${SERVICE} | tr _ -)" --no-editable

FROM python:3.13-slim
ARG SERVICE
ENV SERVICE_MODULE=${SERVICE} PATH=/app/impl-python/.venv/bin:$PATH HTTP_PORT=8080 PYTHONUNBUFFERED=1
COPY --from=build /app/impl-python/.venv /app/impl-python/.venv
RUN useradd --uid 10001 --no-create-home app
USER 10001
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "exec python -m ${SERVICE_MODULE}.main \"$@\"", "--"]
CMD ["serve"]
