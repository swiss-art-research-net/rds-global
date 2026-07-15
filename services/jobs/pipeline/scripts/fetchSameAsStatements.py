import argparse
import os

from SPARQLWrapper import SPARQLWrapper, POST, JSON

from lib.utils import load_config, generate_prefixes_for_SPARQL as generate_prefixes

SAMEAS_QUERY_TEMPLATE = """
{prefixes}
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT DISTINCT ?subject ?value WHERE {{
    GRAPH <{graph}> {{
        {query_part}
        FILTER(isIri(?subject))
        FILTER(isIri(?value))
    }}
}}"""

BATCH_SIZE = 10000

def main(*, dataset, config, endpoint, output_file):
    sparql = SPARQLWrapper(endpoint)
    sparql.setMethod(POST)
    sparql.setReturnFormat(JSON)

    cfg = load_config(config)
    datasets = cfg.get("datasets", {})
    if dataset not in datasets:
        raise ValueError(f"Dataset '{dataset}' not found in configuration file '{config}'.")
    
    dataset_config = datasets[dataset]
    matches_query = dataset_config.get("queries", {}).get("matches")
    if not matches_query:
        print(f"No matches query is set for dataset '{dataset}' in configuration file '{config}'. Skipping fetching sameAs statements.")
        return
    
    prefixes = generate_prefixes(dataset_config.get("prefixes", {}))
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_file, 'w', encoding="utf-8") as f:
        offset = 0
        while True:
            query = SAMEAS_QUERY_TEMPLATE.format(prefixes=prefixes, graph=dataset_config.get("graph"), query_part=matches_query)
            query_with_offset = f"{query.rstrip()} ORDER BY STR(?subject) STR(?value) OFFSET {offset} LIMIT {BATCH_SIZE}"
            sparql.setQuery(query_with_offset)
            results = sparql.query().convert()
            if not results["results"]["bindings"]:
                break
            for result in results["results"]["bindings"]:
                subject = result["subject"]["value"]
                value = result["value"]["value"]
                f.write(f"<{subject}> <http://www.w3.org/2002/07/owl#sameAs> <{value}> .\n")
            offset += BATCH_SIZE
    

   

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch sameAs statements for a given dataset from the endpoint and write them to a file.")
    parser.add_argument("--dataset", required=True, help="The dataset for which to fetch sameAs statements.")
    parser.add_argument("--config", required=True, help="Path to the datasets configuration YAML file.")
    parser.add_argument("--endpoint", required=True, help="The endpoint to query.")
    parser.add_argument("--output-file", required=True, help="The file to write the sameAs statements to.")

    args = parser.parse_args()
    main(
        dataset=args.dataset,
        config=args.config,
        endpoint=args.endpoint,
        output_file=args.output_file
    )
