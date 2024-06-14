# Input variables:
#   DATA_DIRECTORY(String)
#   DATA_URL(String)
#   SKIP_DELETING (true/false)
#   USE_GUNZIP (true/false)
#   SKIP_UNZIPPING (true/false)
#   FILE_FORMAT (String)

set -e
if [ -d "${DATA_DIRECTORY}" ] && [ ! "${SKIP_DELETING}" == true ]; then
    read -p "Do you want to remove previous data from the directory and dowload new ones?" -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]
    then
        exit
    fi
    echo "Delet the old data directory..."
    rm -r -d ${DATA_DIRECTORY}
    echo "Deletion completed."
fi

echo "Creat the new data directory '${DATA_DIRECTORY}'."
mkdir ${DATA_DIRECTORY}

export CURRENT_DIRECTORY=$(pwd)
cd ${DATA_DIRECTORY}

echo "Fetch datasources..."
if [ "${USE_GUNZIP}" == true ]; then
    curl -k ${DATA_URL} -o data.${FILE_FORMAT}.gz # Use instead for MacOS
    # wget ${DATA_URL} -O data.gz # Use instead for Linux
else
    curl -k ${DATA_URL} -o data.zip # Use instead for MacOS
    # wget ${DATA_URL} -O data.zip # Use instead for Linux
fi
echo "Fetching completed."

if [ "${SKIP_UNZIPPING}" != true ]; then
    echo "Unzip datasources..."
    if [ "${USE_GUNZIP}" == true ]; then
        gunzip data.${FILE_FORMAT}.gz
    else
        unzip data.zip
    fi
    echo "Unzipping completed."
fi

cd ${CURRENT_DIRECTORY}