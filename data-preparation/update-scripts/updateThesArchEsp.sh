export DATA_DIRECTORY=./thes-arch-esp-data
export DATA_URL="http://data.culture.fr/thesaurus/data/ark:/67717/T96?includeSchemes=true&format=TURTLE"
export FILE_FORMAT=ttl
export SKIP_UNZIPPING=true
DATA_FORMAT="text/turtle"
NAMED_GRAPH="http://data.culture.fr/thesaurus/resource/ark:/67717/T96/graph"
# ================================================================
if [ -z "${BLAZEGRAPH_ENDPOINT}" ]; then
    BLAZEGRAPH_ENDPOINT="http://localhost:8080/blazegraph/namespace/kb/sparql"
fi
SCRIPT_DIR=$(pwd)
set -e

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

echo "Start script updateThesArchEsp.sh."
# ========================
./_downloadAndUnzip.sh

if [ ! -f "${DATA_DIRECTORY}/data.ttl" ]; then
    mv ${DATA_DIRECTORY}/data.zip ${DATA_DIRECTORY}/data.ttl
fi

echo "Remove old data from the database"

#blazegraph-runner method
echo "DROP GRAPH <${NAMED_GRAPH}>" > tmp.rq
../utils/blazegraph-runner/bin/blazegraph-runner update --journal=${BLAZEGRAPH_PATH} tmp.rq
rm tmp.rq

echo "Upload data to the database"
# ========================

#blazegraph-runner method
../utils/blazegraph-runner/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH} ${DATA_DIRECTORY}/*.${FILE_FORMAT}

echo "Script updateThesArchEsp.sh finished."
