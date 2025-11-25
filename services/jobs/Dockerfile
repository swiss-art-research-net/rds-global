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
RUN rm /etc/nginx/sites-enabled/default || true
RUN printf 'server {\n    listen 80;\n    root /data;\n    autoindex on;\n    location / {\n        try_files $uri $uri/ =404;\n    }\n}\n' > /etc/nginx/conf.d/static.conf

EXPOSE 80

# Run with nginx
WORKDIR /pipeline
ENTRYPOINT ["nginx", "-g", "daemon off;"]