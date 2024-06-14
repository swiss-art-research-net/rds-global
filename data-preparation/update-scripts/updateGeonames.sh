export DATA_DIRECTORY=$(pwd)/geonames-data
export DATA_URL=http://download.geonames.org/all-geonames-rdf.zip
# For the test in the platform put content of 'assets_to_tests' to
# 'runtime/assets' folder, then use follwoing line instead
# export DATA_URL=http://localhost:8084/assets/no_auth/geonames-data/geonames-data.zip
export FILE_FORMAT=nt

NAMED_GRAPH="http://sws.geonames.org/graph"
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
if ! command -v docker &> /dev/null
then
    echo "Docker could not be found please install it before using this script"
    exit
fi

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

if [[ "$OSTYPE" == "darwin"* ]]; then
    gsplit -l 956067 --additional-suffix '.part.nt' ./geonames.nt # For MacOs
else
    split -l 956067 --additional-suffix '.part.nt' ./geonames.nt
fi
cd ${SCRIPT_DIR}

echo "Remove old data from the database"

#blazegraph-runner method
echo "DROP GRAPH <${NAMED_GRAPH}>" > tmp.rq
../utils/blazegraph-runner/bin/blazegraph-runner update --journal=${BLAZEGRAPH_PATH} tmp.rq
rm tmp.rq

echo "Upload data to the database"
# ========================

#blazegraph-runner method
echo "../utils/blazegraph-runner/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH} ${DATA_DIRECTORY}/*.part.${FILE_FORMAT}"
../utils/blazegraph-runner/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH} ${DATA_DIRECTORY}/*.part.${FILE_FORMAT}

echo "Script updateGeonames.sh finished."
