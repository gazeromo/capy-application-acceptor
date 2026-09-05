FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84
RUN apt-get update && apt-get install -y --no-install-recommends bash git bubblewrap ca-certificates util-linux procps && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 1000 --create-home --shell /bin/bash capy && mkdir /workspace && chown 1000:1000 /workspace
COPY --chmod=0755 muse-bin-1.0.3-R2198.1 /usr/local/bin/muse
COPY broker.py /opt/capy/broker.py
COPY probe.py /opt/capy/probe.py
ENV HOME=/home/capy MUSE_NO_AUTO_UPDATE=1 PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
WORKDIR /workspace
CMD ["sleep", "infinity"]
