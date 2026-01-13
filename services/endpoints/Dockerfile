# Dockerfile
FROM nginx:1.27-alpine

RUN apk add --no-cache bash

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /entrypoint.sh

RUN mkdir -p /config
RUN echo "name,port" > /config/endpoints.csv

RUN chmod +x /entrypoint.sh

EXPOSE 80
VOLUME ["/config"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]