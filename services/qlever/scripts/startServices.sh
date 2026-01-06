#!/bin/bash

tail -n +2 services.csv | while IFS=, read -r name port; do
  ./runServer.sh "$name" "$port"
done