FROM python:3.8

RUN apt-get -qq update && \
    apt-get -q -y upgrade && \
    apt-get install -y sudo curl wget locales nginx && \
    rm -rf /var/lib/apt/lists/*
RUN locale-gen en_US.UTF-8

# Install Python packages
RUN pip install rdflib requests

# Install task runner (http://taskfile.dev)
RUN sh -c "$(curl -ssL https://taskfile.dev/install.sh)" -- -d

# Prepare directories and volumes
RUN mkdir /data
VOLUME /data

# Nginx config (optional: disable default site)
ADD ./nginx/mime.types /etc/nginx/conf.d/mime.types
ADD ./nginx/static.conf /etc/nginx/conf.d/static.conf
RUN rm /etc/nginx/sites-enabled/default || true
EXPOSE 80

# Run with nginx
RUN mkdir -p /pipeline
WORKDIR /pipeline
ENTRYPOINT ["nginx", "-g", "daemon off;"]