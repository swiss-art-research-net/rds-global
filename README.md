# RDS-Global

Setup for the SARI Reference Data Service (RDS) Global. This repository contains the Docker configuration and ETL pipeline to setup the RDS Global service. 

The RDS Global service is a reference data service that provides unified access to reference data from multiple sources. 

## Setup

### Prerequisites

- Docker
- Docker Compose
- (for production) A reverse proxy (e.g. Nginx) running on Docker

### Configuration

Copy and edit the provided `.env.example` file to `.env` and customise as required. The default values can be used for development. For production it is recommended to change at least the `HOST_NAME` and `LETSENCRYPT_EMAIL` values.

For acccess to the SIKART data it is necessary to provide a GitHub Username and Personal Access Token that has access to the [sikart-data](https://github.com/swiss-art-research-net/sikart-data) repository via the `GITHUB_USERNAME_SIKART` and `GITHUB_TOKEN_SIKART` environment variables.

~~For local development, set the `COMPOSE_FILE` environment variable to `docker-compose.dev.yml`. This setup does not require a reverse Proxy and exposes the services on the ports specified (default to 8080 for RDS and 8081 for Blazegraph).~~

### Running the service

To start the service run:

```bash
docker compose up -d
```

In Development mode, RDS is then available at `http://localhost:8080`, using the default port numbers.

### Data Pipeline

An ETL Pipeline is provided that takes care of fetching and preparing the external reference data sources. To run the pipeline, execute:

```bash
docker compose exec jobs task
```

This will run the entire pipeline, currently consisting of the following steps:
- Fetching all data sources
- Index all data in QLever
- Generate SameAs statements
- Generate labels
- Reindex source data and generated statements (QLever updates are currently not as performant as reindexing, but this will be improved in the future, at which point this step will be replaced by an update)
- Add data to OpenSearch index

#### Tasks

The pipeline is controlled through the [Task](https://taskfile.dev/#/) runner. The tasks are defined in the `Taskfile.yml` file.

To list available tasks, run:

```sh
docker compose exec jobs task --list
```

This will output a list of tasks:
```
task: Available tasks for this project:
* add-data-to-search-index:                                Add all data to OpenSearch index
* default:                                                 Run entire pipeline
* fetch-all-sameas-statements:                             Fetch data reuired for SameAs statements
* fetch-sameas-statements-for-dataset:                     Fetch SameAs statements for a specified dataset passed as DATASET variable or via CLI argument
* fetch-sameas-statements-for-dataset-from-wikidata:       Fetch SameAs statements from Wikidata for a specified dataset passed as DATASET variable or via CLI argument
* generate-labels:                                         Generate labels for URIs
* generate-sameas-statements:                              Generates SameAs statements between entities
* generate-type-mappings:                                  Generate type mappings for RDS entities
* index-data:                                              Index all data in QLever
* ingest-data-from-folder:                                 Ingest data to QLever from a specified folder. The folder should be passed via CLI argument
* prepare-indexing:                                        Load values from the config yml and pass on to _prepareForIndexing. Dataset name should be passed via DATASET variable or as CLI argument
* prepare-metadata-for-indexing:                           Prepare RDS metadata for indexing
* process-sameas-statements:                               Process SameAs statements
* update-data:                                             Update RDF datasets
* update-individual-dataset:                               Update individual dataset. Dataset name should be passed via DATASET variable or as CLI argument
* verify-data:                                             Verify the validity of the source data or any data in a specified directory passed as CLI argument
```

### Troubleshooting

If QLever index failes due to write permission issues, set the permission of the bind mount directory to user 999 and group 999:

```bash
sudo chown -R 999:999 binds/qlever-index
```

### Data Verification

To verify the validity of the generated data to be ingested, or any other data folder, the `verify-data` task can be used. This will check if the data is in valid NTriples format and if the IRIs are valid. To run the task, execute:

```bash
docker compose exec jobs task verify-data -- /path/to/data
```

If the GND data fails to be verified, it can help to split it into separate files:
```
split -l 1000000 -d -a 3 data.nt data.temp.
```

And then rename the files to have the `.nt` extension:
```
for f in data.temp.*; do mv "$f" "$f.nt"; done
```

## OpenSearch Connector

The OpenSearch integration is exposed to ResearchSpace via a service descriptor at [services/platform/apps/rds/config/services/opensearch_descriptor.ttl](https://github.com/swiss-art-research-net/rds-global/blob/main/services/platform/apps/rds/config/services/opensearch_descriptor.ttl) and backed by the FastAPI proxy at [services/opensearch-connector/app.py](https://github.com/swiss-art-research-net/rds-global/blob/main/services/opensearch-connector/app.py).

When querying the `opensearch` repository through `SERVICE`, use the dedicated search predicates for input parameters:

- `os:searchTerm` for the search string
- `os:searchDataset` to restrict the search to one or more datasets as a comma-separated string, for example `"gnd"` or `"aat,aat"`
- `os:searchLimit` to control the total number of results requested from the connector
- `os:hasTypeClass` to filter by type class

Note that the outer SPARQL `LIMIT` is not passed through to the OpenSearch. If you need to control how many results the connector fetches, use `os:searchLimit` explicitly.

Example:

```sparql
PREFIX os: <http://www.researchspace.com/resource/assets/Ontologies/opensearch#>

SELECT DISTINCT ?prefLabel ?subject ?description ?typeClass ?dataset ?reference ?score WHERE {
  SERVICE <http://platform:8080/sparql?repository=opensearch> {
    ?query os:searchTerm "newton" ;
      os:searchDataset "gnd" ;
      os:searchLimit 100 ;
      os:hasTypeClass "Person", ?typeClass ;
      os:hasScore ?score ;
      os:hasSubject ?subject ;
      os:hasDataset ?dataset ;
      os:hasDescription ?description ;
      os:hasReference ?reference ;
      os:hasPrefLabel ?prefLabel .
  }
}
GROUP BY ?subject ?description ?prefLabel ?typeClass ?dataset ?reference ?score
ORDER BY DESC(?score) (?reference)
LIMIT 100
```
