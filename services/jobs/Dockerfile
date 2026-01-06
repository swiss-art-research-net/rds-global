FROM adfreiburg/qlever:commit-9410312

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv nginx locales raptor2-utils sudo curl wget \
  && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir rdflib requests

# Install task runner
WORKDIR /
RUN sh -c "$(curl -ssL https://taskfile.dev/install.sh)" -- -d

ADD ./nginx/mime.types /etc/nginx/conf.d/mime.types
ADD ./nginx/static.conf /etc/nginx/conf.d/static.conf
RUN rm /etc/nginx/sites-enabled/default || true
EXPOSE 80

RUN mkdir -p /data /pipeline
VOLUME /data
WORKDIR /pipeline
ENTRYPOINT ["nginx", "-g", "daemon off;"]