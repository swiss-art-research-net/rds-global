DATA_FORMAT="application/x-turtle"
# ================================================================
if [ -z "${BLAZEGRAPH_ENDPOINT}" ]; then
    BLAZEGRAPH_ENDPOINT="http://localhost:8081/blazegraph/namespace/kb/sparql"
fi
SCRIPT_DIR=$(pwd)
set -e
# ================================================================

echo "Start script uploadMetadata.sh."
echo "Uploading dataset metadata to blazegraph"
# ========================
export METADATA_NAMED_GRAPH=file:%2F%2F%2F_datasetsMetadata.ttl
curl -D- -L -u guest:guest -H "Content-Type: ${DATA_FORMAT}" --upload-file "./_datasetsMetadata.ttl" -X POST "${BLAZEGRAPH_ENDPOINT}?context-uri=${METADATA_NAMED_GRAPH}"

echo "Uploading ontology extensions to blazegraph"
export ONTOLOGY_NAMED_GRAPH=file:%2F%2F%2Frds-ontologies-description.ttl
curl -D- -L -u guest:guest -H "Content-Type: ${DATA_FORMAT}" --upload-file "./rds-ontologies-description.ttl" -X POST "${BLAZEGRAPH_ENDPOINT}?context-uri=${ONTOLOGY_NAMED_GRAPH}"

echo "Uploading type mappings to blazegraph"
export TYPE_MAPPING_NAMED_GRAPH=http:%2F%2Fschema.swissartresearch.net%2Frds%2Ftype-mapping
curl -D- -L -u guest:guest -H "Content-Type: ${DATA_FORMAT}" --upload-file "./manual-preparation/type-mapping.ttl" -X POST "${BLAZEGRAPH_ENDPOINT}?context-uri=${TYPE_MAPPING_NAMED_GRAPH}"

echo "Script uploadMetadata.sh finished."