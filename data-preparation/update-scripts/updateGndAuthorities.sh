export DATA_DIRECTORY=./gnd-authorities-data
export DATA_URL=https://data.dnb.de/opendata/authorities-gnd_lds.nt.gz
# For the test in the platform put content of 'assets_to_tests' to
# 'runtime/assets' folder, then use follwoing line instead
# export DATA_URL=http://localhost:10214/assets/no_auth/bibliographical-data/bibliographical-data.ttl.gz
export FILE_FORMAT=ttl
DATA_FORMAT="application/x-turtle"
NAMED_GRAPH="https://d-nb.info/gnd/authorities/graph"
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

echo "Start script updateGndAuthorities.sh."
# ========================
USE_GUNZIP=true ./_downloadAndUnzip.sh

echo "Remove old data from the database"

#blazegraph-runner method
echo "DROP GRAPH <${NAMED_GRAPH}>" > tmp.rq
../utils/blazegraph-runner/bin/blazegraph-runner update --journal=${BLAZEGRAPH_PATH} tmp.rq
rm tmp.rq

echo "Upload data to the database"
# ========================

#blazegraph-runner method
../utils/blazegraph-runner/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH} ${DATA_DIRECTORY}/*.${FILE_FORMAT}

echo "Script updateGndAuthorities.sh finished."
echo "Make sure to restart the Blazegraph server to apply the changes."