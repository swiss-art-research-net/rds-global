#!/bin/bash

cd ./DockerImage
mkdir -p ./data
mkdir -p ./output
if [[ "$(docker images -q process_same_as_statements 2> /dev/null)" == "" ]]; then
  echo "Building image"
  docker build --tag process_same_as_statements .
fi
cd ../
