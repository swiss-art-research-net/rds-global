export DATA_DIRECTORY=./thes-arch-esp-data
export DATA_URL="http://data.culture.fr/thesaurus/data/ark:/67717/T96?includeSchemes=true&format=TURTLE"
export FILE_FORMAT=ttl
export SKIP_UNZIPPING=true
DATA_FORMAT="text/turtle"
NAMED_GRAPH=http%3A%2F%2Fdata.culture.fr%2Fthesaurus%2Fresource%2Fark%3A%2F67717%2FT96%2Fgraph
# ================================================================
if [ -z "${BLAZEGRAPH_ENDPOINT}" ]; then
    BLAZEGRAPH_ENDPOINT="http://localhost:8080/blazegraph/namespace/kb/sparql"
fi
SCRIPT_DIR=$(pwd)
set -e
function urldecode() { : "${*//+/ }"; echo -e "${_//%/\\x}"; }
NAMED_GRAPH_DECODED="$(urldecode ${NAMED_GRAPH})"
# ================================================================

echo "Start script updateThesArchEsp.sh."
# ========================
./_downloadAndUnzip.sh

mv ${DATA_DIRECTORY}/data.zip ${DATA_DIRECTORY}/data.ttl

echo "Remove old data from the database"

#blazegraph-runner method
echo "DROP GRAPH <${NAMED_GRAPH_DECODED}>" > tmp.rq
../utils/blazegraph-runner/target/universal/stage/bin/blazegraph-runner update --journal=${BLAZEGRAPH_PATH} tmp.rq
rm tmp.rq

#HTTP method
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

echo "Script updateThesArchEsp.sh finished."
