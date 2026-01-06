FROM adfreiburg/qlever:commit-9410312 
#commit-84156ed
USER root
RUN apt update
RUN apt install -y python3 python3-pip librdf-dev raptor2-utils

RUN mkdir /input
RUN mkdir -p /index/rds

COPY runServer.sh /usr/local/bin/runServer.sh
RUN chmod +x /usr/local/bin/runServer.sh

USER qlever

VOLUME ["/input", "/index"]
WORKDIR /index
EXPOSE 7001
# Run idling
ENTRYPOINT [ "tail", "-f", "/dev/null" ]
