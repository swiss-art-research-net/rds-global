FROM adfreiburg/qlever:commit-f35a290

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv locales raptor2-utils sudo curl wget jq nodejs npm \
  && rm -rf /var/lib/apt/lists/*

# Install yq (v4)
RUN wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_arm64 \
    -O /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq

RUN locale-gen en_US.UTF-8

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir rdflib requests opensearch-py tqdm SPARQLWrapper pyyaml

# Install task runner
WORKDIR /
RUN sh -c "$(curl -ssL https://taskfile.dev/install.sh)" -- -d

RUN mkdir -p /data /pipeline
VOLUME /data
WORKDIR /pipeline
ENTRYPOINT ["tail", "-f", "/dev/null"]