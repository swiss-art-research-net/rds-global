FROM adfreiburg/qlever:commit-9410312 
#commit-84156ed
USER root

COPY ./scripts/runServer.sh /usr/local/bin/runServer.sh
RUN chmod +x /usr/local/bin/runServer.sh

RUN mkdir /index
WORKDIR /index
VOLUME ["/index"]

EXPOSE 7001
# Run idling
ENTRYPOINT [ "sh", "-c", "/usr/local/bin/runServer.sh & tail -f /dev/null" ]