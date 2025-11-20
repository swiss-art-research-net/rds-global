FROM adfreiburg/qlever:commit-9410312
USER root
RUN apt update
RUN apt install -y python3 python3-pip librdf-dev raptor2-utils

RUN mkdir /input
RUN mkdir -p /index/rds
USER qlever

VOLUME ["/input", "/index"]
WORKDIR /index/rds
# Run idling
ENTRYPOINT [ "sh", "-c", "qlever start & tail -f /dev/null" ]