FROM python:3.8

RUN apt-get -qq update && \
    apt-get -q -y upgrade && \
    apt-get install -y sudo curl wget locales && \
    rm -rf /var/lib/apt/lists/*
RUN locale-gen en_US.UTF-8

RUN apt clean
RUN apt update
RUN apt install -y default-jre
# Install Python packages
RUN pip install rdflib requests

# Install Blazegraph Runner
RUN wget -O blazegraph-runner.tgz https://github.com/balhoff/blazegraph-runner/releases/download/v1.7/blazegraph-runner-1.7.tgz
RUN mkdir /utils
RUN tar -xvzf blazegraph-runner.tgz -C /utils
RUN mv /utils/blazegraph-runner-1.7 /utils/blazegraph-runner
RUN rm blazegraph-runner.tgz

# Install task runner (http://taskfile.dev)
RUN sh -c "$(curl -ssL https://taskfile.dev/install.sh)" -- -d

# Prepare directories and volumes
RUN mkdir /pipeline
ADD ./pipeline /pipeline
WORKDIR /pipeline

RUN mkdir /data
VOLUME /data

# Run idling
ENTRYPOINT tail -f /dev/null