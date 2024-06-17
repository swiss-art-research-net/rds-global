ROOT_DIR=$(pwd)
UPDATE_SCRIPTS_DIR=${ROOT_DIR}/update-scripts

# Warning message
echo "WARNING: Please make sure Blazegraph is switched off before running this script to avoid corruption of the blazegraph journal."

# Confirmation prompt
read -p "Are you sure you want to continue? (y/n): " answer
if [[ $answer != "y" ]]; then
    echo "Script execution aborted."
    exit 1
fi

cd ${UPDATE_SCRIPTS_DIR}
./updateAat.sh
./updateGeonames.sh
./updateGndAuthorities.sh
./updateUlan.sh
./updateThesObjMob.sh
./updateSikart.sh
cd ${ROOT_DIR}
./uploadMetadata.sh
