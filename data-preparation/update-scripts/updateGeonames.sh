export DATA_DIRECTORY=$(pwd)/geonames-data
export DATA_URL=http://download.geonames.org/all-geonames-rdf.zip
# For the test in the platform put content of 'assets_to_tests' to
# 'runtime/assets' folder, then use follwoing line instead
# export DATA_URL=http://localhost:10214/assets/no_auth/geonames-data/geonames-data.zip
export FILE_FORMAT=nt
DATA_FORMAT="text/plain"
NAMED_GRAPH=http%3A%2F%2Fsws.geonames.org%2Fgraph
# ================================================================
if [ -z "${BLAZEGRAPH_ENDPOINT}" ]; then
    BLAZEGRAPH_ENDPOINT="http://localhost:8080/blazegraph/namespace/kb/sparql"
fi
SCRIPT_DIR=$(pwd)
set -e
if ! command -v docker &> /dev/null
then
    echo "Docker could not be found please install it before using this script"
    exit
fi
function urldecode() { : "${*//+/ }"; echo -e "${_//%/\\x}"; }
NAMED_GRAPH_DECODED="$(urldecode ${NAMED_GRAPH})"
# ================================================================

echo "Start script updateGeonames.sh."
# ========================
./_downloadAndUnzip.sh

echo "Prepare Geonames data"
# ========================
if [ -d "${DATA_DIRECTORY}/dockerFolder" ]; then
    rm -r -d ${DATA_DIRECTORY}/dockerFolder
fi
mkdir ${DATA_DIRECTORY}/dockerFolder
cp _convert2ntriples.py ${DATA_DIRECTORY}/convert2ntriples.py
cp _dockerfile_to_execute_python ${DATA_DIRECTORY}/dockerFolder/Dockerfile
cd ${DATA_DIRECTORY}/dockerFolder
echo "Building image"
docker build -t rds/converting-geonames:1.0 .
cd ${DATA_DIRECTORY}
docker stop converting-geonames || true && docker rm converting-geonames || true
echo "Running a container with the python script"
docker run -it -v /$(pwd):/usr/src/convertingScriptFolder/ --name converting-geonames rds/converting-geonames:1.0
split -l 956067 --additional-suffix '.part.nt' ./geonames.nt
# gsplit -l 956067 --additional-suffix '.part.nt' ./geonames.nt # For MacOs
cd ${SCRIPT_DIR}

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
../utils/blazegraph-runner/target/universal/stage/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH_DECODED} ${DATA_DIRECTORY}/*.part.${FILE_FORMAT}

#HTTP method
#for filename in ${DATA_DIRECTORY}/*.part.${FILE_FORMAT}; do
#    echo "\nUploading: ".${filename}
#    curl -D- -L -u guest:guest -H "Content-Type: ${DATA_FORMAT}" --upload-file ${filename} -X POST "${BLAZEGRAPH_ENDPOINT}?context-uri=${NAMED_GRAPH}"
#done

echo "Script updateGeonames.sh finished."
