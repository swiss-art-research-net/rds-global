FROM adfreiburg/qlever:commit-9410312 
#commit-84156ed
USER root

COPY ./Qleverfile ./Qleverfile

RUN mkdir /index
WORKDIR /index
VOLUME ["/index"]

EXPOSE 7000
# Run idling
ENTRYPOINT [ "tail", "-f", "/dev/null" ]