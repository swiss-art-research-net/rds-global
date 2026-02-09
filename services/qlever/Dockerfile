FROM adfreiburg/qlever:commit-f35a290 
#commit-84156ed
USER root

RUN mkdir /index
WORKDIR /index
VOLUME ["/index"]

EXPOSE 7001
# Run idling
ENTRYPOINT [ "sh", "-c", "qlever start --name rds --description 'RDS Qlever instance' --system native --port 7001 & tail -f /dev/null" ]