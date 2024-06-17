# Input variables:
#   DATA_DIRECTORY(String)
#   DATA_URL(String)
#   SKIP_DELETING (true/false)
#   USE_GUNZIP (true/false)
#   SKIP_UNZIPPING (true/false)
#   FILE_FORMAT (String)
#   GITHUB_USERNAME (String)
#   GITHUB_TOKEN (String)
#   REPOSITORY_LOCATION (String)
#   REPOSITORY_NAME (String)

#PARAMETERS TO SET IN .env FILE
# GITHUB_USERNAME
# GITHUB_TOKEN

source .env
set -e
if [ -d "${DATA_DIRECTORY}" ] && [ ! "${SKIP_DELETING}" == true ]; then
    read -p "Do you want to remove previous data from the directory and dowload new ones? (y/n)" -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]
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

curl -u ${GITHUB_USERNAME}:${GITHUB_TOKEN} ${DATA_URL} > sha.txt
export SIKART_SHA=$(cat sha.txt | awk -F 'sha256:|\n' '{print $2}' | xargs)
export SIKART_SIZE=$(tail -n 1 sha.txt | awk '{ print $2 }')


if [ "${USE_GUNZIP}" == true ]; then
    curl $(curl -X POST \
    -H "Accept: application/vnd.git-lfs+json" \
    -H "Content-type: application/json" \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -d "{\"operation\": \"download\", \"transfer\": [\"basic\"], \"objects\": [{\"oid\": \"${SIKART_SHA}\", \"size\": ${SIKART_SIZE}} ]}" \
    https://github.com/${REPOSITORY_LOCATION}/${REPOSITORY_NAME}.git/info/lfs/objects/batch | jq -r ".objects | .[0] | .actions | .download | .href") --output data.${FILE_FORMAT}.gz
    #curl -k ${DATA_URL} -o data.${FILE_FORMAT}.gz # Use instead for MacOS
    # wget ${DATA_URL} -O data.gz # Use instead for Linux
else
    curl $(curl -X POST \
    -H "Accept: application/vnd.git-lfs+json" \
    -H "Content-type: application/json" \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -d "{\"operation\": \"download\", \"transfer\": [\"basic\"], \"objects\": [{\"oid\": \"${SIKART_SHA}\", \"size\": ${SIKART_SIZE} } ]}" \
    https://github.com/${REPOSITORY_LOCATION}/${REPOSITORY_NAME}.git/info/lfs/objects/batch | jq -r ".objects | .[0] | .actions | .download | .href") --output data.${FILE_FORMAT}.zip
    #curl -k ${DATA_URL} -o data.zip # Use instead for MacOS
    # wget ${DATA_URL} -O data.zip # Use instead for Linux
fi

rm sha.txt
echo "Fetching completed."

if [ "${SKIP_UNZIPPING}" != true ]; then
    echo "Unzip datasources..."
    if [ "${USE_GUNZIP}" == true ]; then
        gunzip data.${FILE_FORMAT}.gz
    else
        unzip data.${FILE_FORMAT}.zip
    fi
    echo "Unzipping completed."
fi

cd ${CURRENT_DIRECTORY}
