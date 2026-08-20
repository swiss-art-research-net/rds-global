# RDS-Global

Setup for the SARI Reference Data Service (RDS) Global. This repository contains the Docker configuration and ETL pipeline to setup the RDS Global service. 

The RDS Global service is a reference data service that provides unified access to reference data from multiple sources. 

## Setup

### Prerequisites

- Docker
- Docker Compose
- Sufficient memory for local indexing and search services. The current setup allocates 2 GB heap to OpenSearch and up to 12 GB for QLever indexing, so a machine with at least 16 GB RAM is recommended for running the full pipeline locally.
- (for production) A reverse proxy (e.g. Nginx) running on Docker

### Configuration

Copy and edit the provided `.env.example` file to `.env` and customise as required.

This repository is designed to be run with the base compose file plus either the development or production overlay, selected via `COMPOSE_FILE` in `.env`:

- Development: `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml`
- Production: `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`

For development, the default values in `.env.example` can be used as a starting point. For production it is recommended to change at least `PLATFORM_HOST_NAME`, `RECONCILE_HOST_NAME`, `LETSENCRYPT_EMAIL`, and `PROXY_NETWORK_NAME`.

For acccess to the SIKART data it is necessary to provide a GitHub Username and Personal Access Token that has access to the [sikart-data](https://github.com/swiss-art-research-net/sikart-data) repository via the `GITHUB_USERNAME_SIKART` and `GITHUB_TOKEN_SIKART` environment variables.

Important environment variables:

- `DATASETS`: comma-separated list of datasets to fetch and index. Available dataset keys are defined in `config/datasets/*.yml`, and the active subset is assembled into `config/datasets.yml` on startup.
- `QLEVER_ACCESS_TOKEN`: access token used by the QLever API for authenticated update operations.
- `COMPOSE_FILE`: selects which compose file assembly to use for the stack.
- `PLATFORM_HOST_NAME`: public hostname for the ResearchSpace / RDS platform.
- `RECONCILE_HOST_NAME`: public hostname for the OpenSearch reconciliation connector.
- `PROXY_NETWORK_NAME`: name of the external reverse-proxy network used by the production overlay.

The pipeline downloads source data from external services and repositories as configured in the datasets configuration, and queries Wikidata for SameAs generation. A first run therefore requires outbound network access and can take a while depending on the selected datasets.

### Running the service

After choosing the desired `COMPOSE_FILE` assembly in `.env`, start the service with:

```bash
docker compose up -d
```

With the development assembly (`docker-compose.yml:docker-compose.dev.yml`), this starts:

- RDS / ResearchSpace at `http://localhost:8080`
- QLever at `http://localhost:7001`
- OpenSearch Dashboards at `http://localhost:5601`

With the production assembly (`docker-compose.yml:docker-compose.prod.yml`), the stack is attached to the configured external proxy network. The `platform` service is advertised to the reverse proxy via `PLATFORM_HOST_NAME`, and the `opensearch-connector` is advertised separately via `RECONCILE_HOST_NAME`, both using `VIRTUAL_HOST`, `LETSENCRYPT_HOST`, `LETSENCRYPT_EMAIL`, and `VIRTUAL_PORT`. In this mode, both services are expected to be reached through their configured hostnames rather than localhost port mappings.

The OpenSearch connector is started as part of both compose assemblies and is used internally by the ResearchSpace OpenSearch integration. In production it can also be published independently under its own hostname for reconciliation clients.

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
* generate-dataset-metadata:                               Generate dataset metadata RDF
* generate-datasets-configuration:                         Generate the unified datasets configuration
* generate-frontend-configuration:                         Generate configuration for the frontend
* generate-labels:                                         Generate labels for URIs
* generate-sameas-statements:                              Generates SameAs statements between entities
* generate-type-mappings:                                  Generate type mappings for RDS entities
* index-data:                                              Index all data in QLever
* ingest-data-from-folder:                                 Ingest data to QLever from a specified folder. The folder should be passed via CLI argument
* prepare-indexing:                                        Load values from the config yml and pass on to _prepareForIndexing. Dataset name should be passed via DATASET variable or as CLI argument
* prepare-metadata-for-indexing:                           Prepare RDS metadata for indexing
* process-sameas-statements:                               Process SameAs statements
* remove-dataset-from-search-index:                        Remove a dataset from OpenSearch index. Dataset name should be passed via DATASET variable or as CLI argument
* restart-qlever:                                          Request a restart of the QLever service
* startup:                                                 Tasks that run on container startup
* supplement-wikidata-type-mappings:                       Generate and index mappings for Wikidata entities that lack a RDS type based on entities linked via match statements
* update-data:                                             Update RDF datasets
* update-individual-dataset:                               Update individual dataset. Dataset name should be passed via DATASET variable or as CLI argument
* verify-data:                                             Verify the validity of the ingest data or any data in a specified directory passed as CLI argument
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

The setup includes a small FastAPI service at `services/opensearch-connector/app.py` with:

- `POST /search`: accepts a plain search request (`query`, optional `dataset`, optional `typeclass`, and `limit`), fans it out across configured datasets, and translates it into an OpenSearch `_msearch` request.
- result normalisation: flattens per-dataset responses and groups mutually linked records so equivalent entities share a reference id and score.

This connector exists because ResearchSpace’s REST integration can call a simple JSON API more easily than it can build complex OpenSearch queries directly

The OpenSearch integration is exposed to ResearchSpace via a service descriptor at [services/platform/apps/rds/config/services/opensearch_descriptor.ttl](https://github.com/swiss-art-research-net/rds-global/blob/main/services/platform/apps/rds/config/services/opensearch_descriptor.ttl) and backed by the FastAPI proxy at [services/opensearch-connector/app.py](https://github.com/swiss-art-research-net/rds-global/blob/main/services/opensearch-connector/app.py).

When querying the `opensearch` repository through `SERVICE`, use the dedicated search predicates for input parameters:

- `os:searchTerm` for the search string
- `os:searchDataset` to restrict the search to one or more datasets as a comma-separated string, for example `"gnd"` or `"aat,gnd"`
- `os:searchTypeClass` to restrict the search to one or more type classes as a comma-separated string, for example `"Person"` or `"Person,Group"`
- `os:searchLimit` to control the total number of results requested from the connector
- `os:searchTypeClass` to filter by type class

Note that the outer SPARQL `LIMIT` is not passed through to the OpenSearch. If you need to control how many results the connector fetches, use `os:searchLimit` explicitly.

The available predicates for the output are:
- `os:hasDataset` for the dataset
- `os:hasDescription` for the description
- `os:hasLocalMatches` for the local matches (the matches that are defined in the dataset of the result)
- `os:hasMatches` for all the matches
- `os:hasPrefLabel` for the preferred label
- `os:hasReference` for the reference id (shared by all equivalent entities)
- `os:hasScore` for the score (shared by all equivalent entities)
- `os:hasSubject` for the subject (the URI of the entity)
- `os:hasTypeClass` for the type class

Example:

```sparql
PREFIX os: <http://www.researchspace.com/resource/assets/Ontologies/opensearch#>

SELECT DISTINCT ?prefLabel ?subject ?description ?typeClass ?dataset ?reference ?score WHERE {
  SERVICE <http://platform:8080/sparql?repository=opensearch> {
    ?query os:searchTerm "newton" ;
      os:searchDataset "gnd" ;
      os:searchLimit 100 ;
      os:searchTypeClass "Person,Group" ;
      os:hasTypeClass ?typeClass ;
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

## Search Evaluation

The repository includes a small search evaluation runner that executes a CSV query set against the `opensearch-connector` API and writes both a CSV result file and an HTML inspection report.

The query template lives at [services/search-evaluation/tests/search-evaluation-template.csv](./services/search-evaluation/tests/search-evaluation-template.csv).

Run the evaluation with:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm search-evaluation
```

This uses the connector API directly via `POST /search` and requests a larger hit set before ranking results by `_score`.

By default, the run writes:

- [services/search-evaluation/output/search-evaluation-results.csv](/Users/fkraeutli/Sites/rds-global/services/search-evaluation/output/search-evaluation-results.csv)
- [services/search-evaluation/output/search-evaluation-results.html](/Users/fkraeutli/Sites/rds-global/services/search-evaluation/output/search-evaluation-results.html)

Useful environment overrides:

- `SEARCH_EVAL_LIMIT=100` to control how many hits are requested from the connector before top results are evaluated
- `SEARCH_EVAL_DATASET=gnd` to restrict the test run to a single dataset, or for example `SEARCH_EVAL_DATASET=aat,gnd`
- `SEARCH_EVAL_TIMEOUT=30` to adjust the request timeout in seconds


### Troubleshooting

#### Setup

If QLever index failes due to write permission issues, set the permission of the bind mount directory to user 999 and group 999:

```bash
sudo chown -R 999:999 binds/qlever
```


If a task in the default pipline run fails, restart it by calling it directly with `task <task-name>`. Then execute the following tasks in the order they are defined in the default pipeline, until the pipeline is complete again. This is necessary because some tasks depend on the output of previous tasks, for example the OpenSearch indexing depends on the generated SameAs statements and labels.

If the indexing to the OpenSearch Index is incomplete, it is possible to continue it from a given offset.
