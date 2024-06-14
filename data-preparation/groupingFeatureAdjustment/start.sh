#!/bin/bash

export BLAZEGRAPH_ENDPOINT="http://localhost:8081/blazegraph/sparql"
export WIKIDATA_ENDPOINT="https://query.wikidata.org/sparql"

echo "Build Image if not exists"
./buildImage.sh

echo "Fetching data"
./fetchData.sh

echo "Processing data"
./processData.sh
