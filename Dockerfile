FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PIP_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple \
    PYTHONPATH=/opt/python-deps

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY .azure/python-deps /opt/python-deps
COPY budget_agent ./budget_agent

EXPOSE 8000
CMD ["python", "-m", "budget_agent.server"]
