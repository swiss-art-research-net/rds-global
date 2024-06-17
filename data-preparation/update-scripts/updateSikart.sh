#!/bin/bash
#   GITHUB_USERNAME (String)
#   GITHUB_TOKEN (String)
export DATA_DIRECTORY=$(pwd)/sikart-data
export DATA_URL="https://raw.githubusercontent.com/swiss-art-research-net/sikart-data/main/source/SIK_20210616_2300.ttl.zip"
# For the test in the platform put content of 'assets_to_tests' to
# 'runtime/assets' folder, then use follwoing line instead
# export DATA_URL=http://localhost:10214/assets/no_auth/t.b.d.
export FILE_FORMAT=ttl
export SKIP_DELETING=false
export USE_GUNZIP=false
export SKIP_UNZIPPING=false
export REPOSITORY_LOCATION="swiss-art-research-net"
export REPOSITORY_NAME="sikart-data"
DATA_FORMAT="application/x-turtle"
NAMED_GRAPH="http://recherche.sik-isea.ch/graph"
# ================================================================
if [ -z "${BLAZEGRAPH_PATH}" ]; then
    echo "BLAZEGRAPH_PATH is not set. Using default location in ../data/blazegraph-data/blazegraph.jnl"
    export BLAZEGRAPH_PATH=../../data/blazegraph-data/blazegraph.jnl
fi
# Check if Blazegraph Runner is present in ../utils/blazegraph-runner/bin
if [ ! -f "../utils/blazegraph-runner/bin/blazegraph-runner" ]; then
    echo "Blazegraph Runner is not present. Downloading it now."
    ./_downloadBlazegraphRunner.sh
fi

SCRIPT_DIR=$(pwd)
set -e

# ================================================================

echo "Start script updateSikart.sh."
# ========================
./_downloadSecureLfsAndUnzip.sh
#start=`date +%`

echo "Remove old data from the database"

#blazegraph-runner method
echo "DROP GRAPH <${NAMED_GRAPH}>" > tmp.rq
../utils/blazegraph-runner/bin/blazegraph-runner update --journal=${BLAZEGRAPH_PATH} tmp.rq
rm tmp.rq

#end=`date +%s`
#echo Execution time for deletion was `expr $end - $start` seconds.

echo "Upload data to the database"

#start=`date +%s`
# ========================

#blazegraph-runner method
../utils/blazegraph-runner/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH} ${DATA_DIRECTORY}/*.${FILE_FORMAT}

#end=`date +%s`

echo "Script updateSikart.sh finished."
echo "Make sure to restart the Blazegraph server to apply the changes."

#echo Execution time for graph uplodad was `expr $end - $start` seconds.
