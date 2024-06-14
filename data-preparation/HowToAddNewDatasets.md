# How to add new datasets

To add a new dataset the following steps need to be followed:

1. Create a new script for downloading the data from the source and upload it to the Blazegraph instance
    * The scripts are located in `/data-preparation/update-scripts/`. They need to be tailored to the specific format of the dataset and the way it is provided.  The AAT dataset, for example, is downloaded as a zip file, extracted, and ingested as is. The GND data on the other hand undergoes some preprocessing. Use a suitable existing script as an example and adapt as required.The `updateAat.sh` is a good start. Configure the variables at the start of the script as needed. Be sure to update and keep a note of the `NAMED_GRAPH` variable, which defines the named graph where the data will be ingested to.
1. Add the newly created script to the `data-preparation/updateAll.sh` script
1. Add a Lookup service for the new dataset.
    * Use one of the existing configurations in `rds-global/config/repositories` as a start. Choose a unique ID for the lookup service, which needs to match the file name. Adapt the dataset query to match the named graph for the dataset. Configure the searchBlockTemplate and adapt it to search in the correct label of the entities.
1. Add an entry on the Start page to allow search in only the newly created dataset.
    * Copy and edit one of the other `bs-nav` links and corresponding `bs-tab-pane` element.
1. Add the dataset metadata to the `data-preparation/_datasetsMetadata.ttl` file. This will be used to display information about the dataset as well as a thumbnail.
1. Upload the dataset using the previously created script. After uploading, the default lookup should already be able to find entities.
1. It might be necessary to configure the default lookup, such as when the wrong type of entities appear or none at all (in the latter case, it's best to first check whether all data is actually present). 
    * Edit the `rds-global/config/repositories/default-lookup.ttl` configuration
1. If your dataset introduces a new type, it might be necessary to add it.
    * Edit `data-preparation/manual-preparation/type-mapping.ttl` to include your type and upload it to the named graph `<http://schema.swissartresearch.net/rds/type-mapping>`
1. In order to include the new dataset in the grouping/aggregation function it needs to be added to the `data-preparation/groupingFeatureAdjustment/fetchData.sh` script.
    * Copy one of the existing examples and configure it to search in the specified named graph and match using the predicate used in the dataset for representing sameAs type statements.
1. Update the RDS-G (staging) instance with the new and changed files.
1. Run the grouping script in `data-preparation/groupingFeatureAdjustment/start.sh`