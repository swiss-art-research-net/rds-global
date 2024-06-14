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
    echo "BLAZEGRAPH_PATH is not set. Using default location in ../data/blazegraph-data/blazegraph.jnl"
    export BLAZEGRAPH_PATH=../data/blazegraph-data/blazegraph.jnl
fi

# Check if Blazegraph Runner is present in ../utils/blazegraph-runner/bin
if [ ! -f "../utils/blazegraph-runner/bin/blazegraph-runner" ]; then
    echo "Blazegraph Runner is not present. Downloading it now."
    ./_downloadBlazegraphRunner.sh
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

echo "DROP GRAPH <${NAMED_GRAPH_DECODED}>" > tmp.rq
../utils/blazegraph-runner/bin/blazegraph-runner update --journal=${BLAZEGRAPH_PATH} tmp.rq
rm tmp.rq

echo "Upload data to the database"
# ========================

#blazegraph-runner method
../utils/blazegraph-runner/bin/blazegraph-runner load --journal=${BLAZEGRAPH_PATH} --graph=${NAMED_GRAPH_DECODED} ${DATA_DIRECTORY}/*.${FILE_FORMAT}

echo "Script updateAat.sh finished."


