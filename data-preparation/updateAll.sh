ROOT_DIR=$(pwd)
UPDATE_SCRIPTS_DIR=${ROOT_DIR}/update-scripts
LABEL_SCRIPTS_DIR=${ROOT_DIR}/labelAdjustments
GROUPING_FEATURE_DIR=${ROOT_DIR}/groupingFeatureAdjustments

if [ -z "${BLAZEGRAPH_PATH}" ]; then
    echo "BLAZEGRAPH_PATH is not set. Using default location in ../data/blazegraph-data/blazegraph.jnl"
    export BLAZEGRAPH_PATH=../../data/blazegraph-data/blazegraph.jnl
fi

# Warning message
echo "WARNING: Please make sure Blazegraph is switched off before running this script to avoid corruption of the blazegraph journal."

# Confirmation prompt
read -p "Are you sure you want to continue? (y/n): " answer
if [[ $answer != "y" ]]; then
    echo "Script execution aborted."
    exit 1
fi

echo "Running data update scripts..."

cd ${UPDATE_SCRIPTS_DIR}
./updateAat.sh
./updateGeonames.sh
./updateGndAuthorities.sh
./updateSikart.sh
./updateThesArchEsp.sh
./updateThesObjMob.sh
./updateUlan.sh
./updateSikart.sh
cd ${ROOT_DIR}

echo "Running label update scripts..."
cd ${LABEL_SCRIPTS_DIR}
./labelAdjustments/adjustLabels.sh -p all_predicates.txt -b ${BLAZEGRAPH_PATH}
cd ${ROOT_DIR}

# Notify user that Blazegraph that they now need to restart blazegraph and confirm before continuing
echo "Please restart Blazegraph to continue."
read -p "Have you restarted Blazegraph? (y/n): " answer
if [[ $answer != "y" ]]; then
    echo "Script execution aborted."
    exit 1
fi

echo "Uploading metadata..."
./uploadMetadata.sh

echo "Generating groups..."
cd ${GROUPING_FEATURE_DIR}
./start.sh