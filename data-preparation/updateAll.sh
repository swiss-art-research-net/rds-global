ROOT_DIR=$(pwd)
UPDATE_SCRIPTS_DIR=${ROOT_DIR}/update-scripts

cd ${UPDATE_SCRIPTS_DIR}
./updateAat.sh
./updateGeonames.sh
./updateGndAuthorities.sh
./updateUlan.sh
./updateThesObjMob.sh
./updateSikart.sh
cd ${ROOT_DIR}
./uploadMetadata.sh
