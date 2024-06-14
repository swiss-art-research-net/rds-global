# How to use the uploading scripts
To download and upload all datasets to your Blazegraph database execute `updateAll.sh`. This script automatically fetches, converts and uploads all necessary data. You can use scripts from the `update-scripts` folder to update only specific datasets (scripts to use: `updateAat.sh`, `updateGeonames.sh`, `updateGndAuthorities.sh`). All scripts starting with an underscore are internal and are not meant to be executed manually.

### Requirements
Before using this script you should ensure you have 'sed' and 'docker' and 'jq' installed on you system. Typically 'docker' and 'sed' are installed. So use `apt-get` or `yum` to install 'jq' before using the scripts.

### Example
```
export BLAZEGRAPH_ENDPOINT=http://rds-mph-blazegraph:8080/blazegraph/sparql

./updateAll.sh
```
or
```
BLAZEGRAPH_ENDPOINT=http://rds-mph-blazegraph:8080/blazegraph/sparql ./updateAll.sh
```

## Import mappings
To use mappings with uploaded datasets import `./manual-preparation/type-mapping.ttl` into the following named graph `<http://schema.swissartresearch.net/rds/type-mapping>`.

## Wikidata mappings
The mappings for Wikidata are defined in the files `{root}/rds-global/config/repositories/wikidata-lookup.ttl` and `{root}/rds-global-dev/config/repositories/wikidata-lookup.ttl`. You can update them by changing the `lookup:typeBlockTemplate` parameter. If `type-mapping.ttl` is uploaded, you can use `./manual-preparation/generate-type-mappings-for-wikidata.sparql` script to generate a `VALUES` clause based on the information from the `ttl` file.

## Update type mappings
To change mappings update `./manual-preparation/type-mapping.ttl` and then reimport them as it described in the "Import mappings" paragraph.

# Dataset labels and images
To assign dataset metadata to datasets via SPARQL execute the `INSERT` query from `./manual-preparation/dataset-metadata.sparql` or upload the file `./data-preparation/_datasetsMetadata.ttl` into your database.

# Workflow definitions for RDS-L
For the **rds-local** you will need also upload `./example-workflow-container.trig` and `example-workflow-definition.trig` as ldp resource to the platform (use interface on the following page: [example on the rds-mph](https://rds-local-mph.swissartresearch.net/resource/Platform:rootContainer?repository=assets). RDS-L configuration and documentation which describes how to deploy the service is stored here: https://github.com/swiss-art-research-net/rds-local. In case you use rds-local-demo application files `./example-workflow-container.trig` and `example-workflow-definition.trig`should be bootstrapped automatically as ldp resources.

# Grouping feature
Some Search components support grouping related elements from different datasets. This feature is implemented based on the `same-as` information which is contained in a dedicated namedGraph. 

To prepare this graph and get the benefits from this feature you have to prepare this data manually using this guide. Use this guide after all datasets have been uploaded into the main data repository. All `same-as` information will be compiled from the main set of the data.

Compiling `same-as` information is performed using the following steps:
1. Navigate to the folder `./groupingFeatureAdjustment/`.
2. Find script `start.sh` and set values of the environment variables `BLAZEGRAPH_ENDPOINT` and `WIKIDATA_ENDPOINT`:
```
export BLAZEGRAPH_ENDPOINT="https://rds-qa.swissartresearch.net/sparql"
export WIKIDATA_ENDPOINT="https://query.wikidata.org/sparql"
```
3. Execute `start.sh` to fetch and process the data:
```
./start.sh
```
4. As a result you will get two new folders in the script folder: `data` and `output`. The folder `data` will contain the set of files from different datasets in the shape as they were represented in the original datasets. `output` will contain a set of files `result_0.ttl`, `result_1.ttl` ... `result_N.ttl`. In this file the structure is flattened without transitive relations and cycles: for each group of related resources there is a single primary entity which has outgoing statements with predicate `rds:sameAs` to the other resources of the group.
5. Upload all result files into your database as a separate namedGraph. You can do it manually or you can use `./uploadAll.sh` file. To use `./uploadAll.sh` you have to specify `BLAZEGRAPH_ENDPOINT` and `NAMED_GRAPH` variables first. Then just put this file into the `output` directory and execute it.

## Structure of processing scripts
The processing scripts separated in the number of files divided by steps they do:
* `start.sh` calls:
    * `buildImage.sh` - builds the Docker Image to use it on the data processing step
    * `fetchData.sh` - fetches data from Wikidata and the target SPARQL endpoint and stores it as a set of files in the `./data` folder
    * `processData.sh` - runs a Docker container with a script to process the data contained in the `./data` folder. You can provide `BLAZEGRAPH_ENDPOINT` and `WIKIDATA_ENDPOINT` environment variables to the script to configure the SPARQL endpoint from which to fetch data.

You can use these scripts via `start.sh` or one by one in case the process failed on the some specific step to prevent already performed steps to be executed twice.

## Troubleshooting
* Each `sh-script` file for this guide was tested on a Windows machine, so for other operation systems possibly you will need to change the file type using command like: ```chmod +x script-name-here.sh```.
* Data from Wikidata and the SPARQL endpoint may contain invalid IRIs, so the processing application may fail to parse the data. The application will give you a hint what and where it went wrong, so it can be manually adjusted and repeated. We recommend for this case to copy `./data` folder and process data file by file using `./processData.sh`. So you can remove files which passed the checking procedure and execute the script only for unchecked files. Once all files have been removed you can restore the data folder from the copy and process all files in one run. (Make sure to clean up the `./output` folder before running the final data processing step).
* Building the Docker image for processing the data on the target server can go wrong because of insufficient permissions on the server side, so we recommend to execute this script from the local machine, or build the image locally and then transfer it to the server for execution.
* On the data fetching step you can face a problem with fetching complete results, i.e. because of the query-timeout limitations or the limitation on the size of fetched data the fetched files can be incomplete or may contain exception messages at the ends of the file. In that case you can fetch smaller portions of the data by modifying `./fetchAll.sh`. For this purpose you have to update the respective `SPARQL-query` in the target `curl-query` to use `OFFSET`, `LIMIT` and `ORDER BY` parameters. Remember without `ORDER BY` parameter you can't be sure that the portions of the files will contain no duplications in data and will cover all the data. Please refer to other queries in `./fetchData.sh` for examples.
