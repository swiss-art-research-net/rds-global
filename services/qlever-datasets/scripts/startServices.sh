#!/bin/bash

tail -n +2 endpoints.csv | while IFS=, read -r name port; do
  ./runServer.sh "$name" "$port" &
done
wait