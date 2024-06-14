export DATA_DIRECTORY=./aat-data
export DATA_URL=http://aatdownloads.getty.edu/VocabData/explicit.zip
# For the test in the platform put content of 'assets_to_tests' to
# 'runtime/assets' folder, then use follwoing line instead
# export DATA_URL=http://localhost:10214/assets/no_auth/aat-data/aat-data.zip
export FILE_FORMAT=nt
DATA_FORMAT="text/plain"
NAMED_GRAPH=http%3A%2F%2Fvocab.getty.edu%2Faat%2Fgraph
# ================================================================
if [ -z "${BLAZEGRAPH_PATH}" ]; then
    echo "BLAZEGRAPH_PATH is not set. Please set BLAZEGRAPH_PATH in the environment variable."
    exit 1
fi
SCRIPT_DIR=$(pwd)
set -e
if ! command -v sed &> /dev/null
then
    echo "'sed' could not be found please install it before using this script"
    exit
fi
function urldecode() { : "${*//+/ }"; echo -e "${_//%/\\x}"; }
NAMED_GRAPH_DECODED="$(urldecode ${NAMED_GRAPH})"
# ================================================================

echo "Start script updateAat.sh."
./_downloadAndUnzip.sh

echo "Prepare AAT data"
# ========================
cd ${DATA_DIRECTORY}
touch "AATOut_WikidataCoref_temp.nt"
cp -p AATOut_WikidataCoref.nt "AATOut_WikidataCoref_temp.nt"
sed -e 's/>[\x0D|\x0A]/> ./g' "AATOut_WikidataCoref_temp.nt" > AATOut_WikidataCoref.nt
echo " ." >> AATOut_WikidataCoref.nt
# sed -e 's/\(Q.*\)>/\1>./g' "AATOut_WikidataCoref_temp.nt" > AATOut_WikidataCoref.nt # For MacOS
rm "AATOut_WikidataCoref_temp.nt"
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
../utils/blazegraph-runner/target/universal/stage/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH_DECODED} ${DATA_DIRECTORY}/*.${FILE_FORMAT}

#HTTP method
#for filename in ${DATA_DIRECTORY}/*.${FILE_FORMAT}; do
#    echo "\nUploading: ".${filename}
#    curl -D- -L -u guest:guest -H "Content-Type: ${DATA_FORMAT}" --upload-file ${filename} -X POST "${BLAZEGRAPH_ENDPOINT}?context-uri=${NAMED_GRAPH}"
#done

echo "Script updateAat.sh finished."


