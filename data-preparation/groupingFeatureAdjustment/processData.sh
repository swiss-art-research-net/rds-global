#!/bin/bash
mkdir -p ./data
mkdir -p ./output

# the container image 'process_same_as_statements' needs to be built using ./buildImage.sh
docker run --rm -it -v ${PWD}/data:/usr/src/app/data -v ${PWD}/output:/usr/src/app/output process_same_as_statements
