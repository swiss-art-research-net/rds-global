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

For local development, set the `COMPOSE_FILE` environment variable to `docker-compose.dev.yml`. This setup does not require a reverse Proxy and exposes the services on the ports specified (default to 8080 for RDS and 8081 for Blazegraph).

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

This will run the entire pipeline, consisting of the following steps:
- Fetching all data sources
- Extracting unique labels for all entities
- Extracting sameas links for all entities
- Loading the data into the Blazegraph triple store

#### Tasks

The pipeline is can be controlled by the [Task](https://taskfile.dev/#/) runner. The tasks are defined in the `Taskfile.yml` file.

To list available tasks, run:

```sh
docker compose exec jobs task --list
```

This will output a list of tasks:
```
task: Available tasks for this project:
* default:                                   Run entire pipeline
* fetch-all-sameas-statements:               Fetch data reuired for SameAs statements
* fetch-sameas-statements-aat:               Fetch SameAs statements contained in AAT
* fetch-sameas-statements-gnd:               Fetch SameAs statements contained in GND
* fetch-sameas-statements-sikart:            Fetch SameAs statements contained in SIKART
* fetch-sameas-statements-thesarchesp:       Fetch SameAs statements contained in Thesaurus Architecture/Espace
* fetch-sameas-statements-thesobjmob:        Fetch SameAs statements contained in Thesaurus Object/Mobiliers
* fetch-sameas-statements-ulan:              Fetch SameAs statements contained in ULAN
* fetch-sameas-statements-wikidata:          Fetch SameAs statements from Wikidata
* generate-labels:                           Generate labels for URIs
* generate-sameas-statements:                Generates SameAs statements between entities
* ingest-metadata:                           Ingest metadata
* ingest-sameas-statements:                  Ingest SameAs statements
* process-sameas-statements:                 Process SameAs statements
* update-data-aat:                           Update data for Getty AAT
* update-data-geonames:                      Update data for GeoNames
* update-data-gnd:                           Update data for GND
* update-data-sikart:                        Update data for SIKART
* update-data-thesarchesp:                   Update data for Thesaurus Architecture/Espace
* update-data-thesobjmob:                    Update data for Thesaurus Object/Mobiliers
* update-data-ulan:                          Update data for Getty ULAN
```