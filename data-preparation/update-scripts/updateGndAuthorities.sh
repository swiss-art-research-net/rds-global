export DATA_DIRECTORY=./gnd-authorities-data
export DATA_URL=https://data.dnb.de/opendata/authorities-gnd_lds.nt.gz
# For the test in the platform put content of 'assets_to_tests' to
# 'runtime/assets' folder, then use follwoing line instead
# export DATA_URL=http://localhost:10214/assets/no_auth/bibliographical-data/bibliographical-data.ttl.gz
export FILE_FORMAT=ttl
DATA_FORMAT="application/x-turtle"
NAMED_GRAPH=https%3A%2F%2Fd-nb.info%2Fgnd%2Fauthorities%2Fgraph
# ================================================================
if [ -z "${BLAZEGRAPH_ENDPOINT}" ]; then
    BLAZEGRAPH_ENDPOINT="http://localhost:8080/blazegraph/namespace/kb/sparql"
fi
SCRIPT_DIR=$(pwd)
set -e
function urldecode() { : "${*//+/ }"; echo -e "${_//%/\\x}"; }
NAMED_GRAPH_DECODED="$(urldecode ${NAMED_GRAPH})"
# ================================================================

echo "Start script updateGndAuthorities.sh."
# ========================
USE_GUNZIP=true ./_downloadAndUnzip.sh

echo "Remove old data from the database"

#blazegraph-runner method
echo "DROP GRAPH <${NAMED_GRAPH_DECODED}>" > tmp.rq
../utils/blazegraph-runner/target/universal/stage/bin/blazegraph-runner update --journal=${BLAZEGRAPH_PATH} tmp.rq
rm tmp.rq

#HTTP method
#echo "Remove old data from the database"
#curl --location --request POST "${BLAZEGRAPH_ENDPOINT}" \
#--header 'Content-Type: application/x-www-form-urlencoded' \
#--data-urlencode "update=DROP GRAPH <${NAMED_GRAPH_DECODED}>"

echo "Upload data to the database"
# ========================

#blazegraph-runner method
../utils/blazegraph-runner/target/universal/stage/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH_DECODED} ${DATA_DIRECTORY}/*.${FILE_FORMAT}

#HTTP method
#for filename in ${DATA_DIRECTORY}/*.${FILE_FORMAT}; do
#    echo "\nUploading: ".${filename}
#    curl -D- -L -u guest:guest -H "Content-Type: ${DATA_FORMAT}" --upload-file ${filename} -X POST "${BLAZEGRAPH_ENDPOINT}?context-uri=${NAMED_GRAPH}"
#done

echo "Script updateGndAuthorities.sh finished."
