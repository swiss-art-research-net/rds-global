FROM python:3.8

RUN apt-get -qq update && \
    apt-get -q -y upgrade && \
    apt-get install -y sudo curl wget locales raptor2-utils && \
    rm -rf /var/lib/apt/lists/*
RUN locale-gen en_US.UTF-8

# Install Python packages
RUN pip install rdflib requests

# Install task runner (http://taskfile.dev)
RUN sh -c "$(curl -ssL https://taskfile.dev/install.sh)" -- -d

# Prepare directories and volumes
RUN mkdir /data
VOLUME /data

# Run with nginx
RUN mkdir -p /pipeline
WORKDIR /pipeline
ENTRYPOINT ["tail", "-f", "/dev/null"]