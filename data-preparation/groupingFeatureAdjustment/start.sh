#!/bin/bash

if [ -z "${BLAZEGRAPH_ENDPOINT}" ]; then
    export BLAZEGRAPH_ENDPOINT="http://localhost:8081/blazegraph/sparql"
fi
export WIKIDATA_ENDPOINT="https://query.wikidata.org/sparql"

echo "Build Image if not exists"
./buildImage.sh

echo "Fetching data"
./fetchData.sh

echo "Processing data"
./processData.sh
