import argparse

from SPARQLWrapper import SPARQLWrapper, POST, JSON
from lib.utils import RDS_ONTOLOGY_NAMESPACE, load_config, generate_prefixes_for_SPARQL as generate_prefixes, RDS_GRAPH_NAMESPACE, RDS_ONTOLOGY_NAMESPACE

PAGE_SIZE = 3000000
PREDICATE =  f"<{RDS_ONTOLOGY_NAMESPACE}related>"


def main(*, endpoint, wikidata_endpoint, output_directory, page_size=PAGE_SIZE, config=None, dataset=None):
    
    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)

    cfg = load_config(config)
    datasets = cfg.get("datasets", {})

    file_num = 0

    # if dataset is specified, limit to that dataset
    if dataset:
        if dataset in datasets:
            datasets = {dataset: datasets[dataset]}
        else:
            print(f"Dataset {dataset} not found in config")
            return

    for dataset in datasets.keys():
        print(f"Processing dataset: {dataset}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    parser = argparse.ArgumentParser(description = 'Fetch matches for a dataset from Wikidata and store them.')
    parser.add_argument('--endpoint',required=True, help='SPARQL endpoint to use for querying the entities')
    parser.add_argument('--wikidata-endpoint', required=False, default='https://query.wikidata.org/sparql', help='SPARQL endpoint to use for querying Wikidata')
    parser.add_argument('--output-directory', required=False, default='/data/sameAsStatements/sources', help='directory to store output files')
    parser.add_argument('--page-size', required=False, type=int, default=3000000, help='number of results to fetch per query')
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--dataset", required=False, help="Dataset to generate labels for (all datasets if not specified)")
    
    args = parser.parse_args()
    endpoint = args.endpoint
    output_directory = args.output_directory
    config = args.config
    dataset = args.dataset if args.dataset else None
    wikidata_endpoint = args.wikidata_endpoint
 
    page_size = args.page_size
    main(endpoint=endpoint, wikidata_endpoint=wikidata_endpoint, output_directory=output_directory, page_size=page_size, config=config, dataset=dataset)