FROM node:24.9.0-alpine AS dashboard-builder
WORKDIR /build/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --ignore-scripts
COPY dashboard/ ./
COPY fixtures/episode1/public-aggregate.fixture.json /build/fixtures/episode1/public-aggregate.fixture.json
COPY fixtures/episode1/episode1-planning.json /build/fixtures/episode1/episode1-planning.json
RUN npm run build

FROM python:3.12.12-slim AS runtime
WORKDIR /app
RUN useradd --create-home --uid 10001 inference-lab
COPY --chown=inference-lab:inference-lab src/ ./src/
COPY --chown=inference-lab:inference-lab scripts/episode1_playground.py ./scripts/episode1_playground.py
COPY --chown=inference-lab:inference-lab dashboard/src/data/episode-tests.v1.json ./dashboard/src/data/episode-tests.v1.json
COPY --from=dashboard-builder --chown=inference-lab:inference-lab /build/dashboard/dist ./dashboard/dist
USER inference-lab
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2)"]
ENTRYPOINT ["python", "/app/scripts/episode1_playground.py"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765", "--profiles", "/config/profiles.json", "--dashboard-dir", "/app/dashboard/dist"]
