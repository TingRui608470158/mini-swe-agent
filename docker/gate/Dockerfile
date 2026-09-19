# Build context = repo root. Requires `python -m quantharness.split data/ build/segments/` first.
#   docker build -f docker/gate/Dockerfile -t quantharness-gate .
#   docker run --network none --rm -it quantharness-gate bash
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends sudo && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home agent \
    && pip install --no-cache-dir "pandas>=2.2" "numpy>=1.26" typer requests

COPY --chmod=0644 src/quantharness /gate/src/quantharness
ENV PYTHONPATH=/gate/src

# train is readable by the agent; validation only by root (the gate); holdout is never copied in.
COPY --chmod=0644 build/segments/train /data/train
COPY build/segments/validation /data/validation
RUN chmod 0700 /data/validation && chmod 0600 /data/validation/*

COPY --chmod=0644 build/segments/split.json docker/gate/config.json /gate/
COPY --chmod=0755 docker/gate/gate /gate/bin/gate
COPY --chmod=0440 docker/gate/sudoers /etc/sudoers.d/gate
RUN mkdir -m 0700 /gate/state \
    && python -c "import json, pathlib; c = json.loads(pathlib.Path('/gate/config.json').read_text()); pathlib.Path('/gate/state/budget.json').write_text(json.dumps({'remaining': c['budget']}))" \
    && mkdir /workspace && chown agent:agent /workspace

WORKDIR /workspace
USER agent
