#!/bin/bash

tail -n +2 /config/endpoints.csv | while IFS=, read -r name port; do
  ./runServer.sh "$name" "$port" &
done
wait