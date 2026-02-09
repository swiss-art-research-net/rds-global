import os
import argparse
import json
import yaml

from SPARQLWrapper import SPARQLWrapper, POST, JSON

LABEL_PREDICATE = "<http://schema.swissartresearch.net/ontology/rds#label>"
LABEL_GRAPH = "<http://schema.swissartresearch.net/rds/labels>"
PAGE_SIZE = 3000000

def main(*, endpoint, output_directory, limit_graph=None, page_size=PAGE_SIZE, config=None, dataset=None):
    
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
        graph = datasets[dataset].get("graph")
        predicates = datasets[dataset].get("queries", {}).get("prefLabel")
        if graph and predicates:
            counter = 0
            # check if predicates is a list or a string
            if type(predicates) == list:
                predicates_path = ' | '.join(predicates)
                predicates_query = '?subject ' + predicates_path + ' ?value .'
            elif type(predicates) == str:
                predicates_query = predicates
            hasResults = True
            while hasResults:
                prefixes = _generate_prefixes(datasets[dataset].get("prefixes", {}))
                query = prefixes + """
                SELECT ?subject ?value WHERE {{
                    GRAPH <{0}> {{
                        {1}
                    }}
                }} ORDER BY DESC(?subject) OFFSET {2} LIMIT {3}
                """.format(graph, predicates_query, str(counter), str(page_size))
                counter = counter + page_size

                sparql.setQuery(query)
                results = sparql.query().convert()
                # if no results, continue to next graph
                if len(results["results"]["bindings"]) == 0:
                    hasResults = False
                    continue
                nquad_lines = []
                for result in results["results"]["bindings"]:
                    subject = result["subject"]["value"]
                    value = result["value"]["value"]
                    subject_str = f"<{subject}>" if result["subject"]["type"] == "uri" else f"\"{subject}\""
                    value_str = f"\"{value}\""
                    # Add datatype or language if present
                    if "xml:lang" in result["value"]:
                        value_str += f"@{result['value']['xml:lang']}"
                    elif "datatype" in result["value"]:
                        value_str += f"^^<{result['value']['datatype']}>"
                    predicate_str = "<http://schema.swissartresearch.net/ontology/rds#label>"
                    graph_str = f"<http://schema.swissartresearch.net/rds/labels>"
                    nquad_line = f"{subject_str} {predicate_str} {value_str} {graph_str} .\n"
                    nquad_lines.append(nquad_line)
                graph_for_filename = graph.replace("http://", "").replace("https://", "").replace("/", "_").replace(":", "_")
                out_path = f"{output_directory}/labels_{graph_for_filename}_{file_num}.nq"
                with open(out_path, "w") as out_f:
                    out_f.writelines(nquad_lines)

                file_num = file_num + 1
            
def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
    
def _generate_prefixes(prefixes):
    items = sorted(prefixes.items(), key=lambda kv: kv[0])
    return "\n".join([f"PREFIX {p}: <{uri}>" for p, uri in items])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    parser = argparse.ArgumentParser(description = 'Produce ttl files with entities and their labels using a unified RDS predicate <http://schema.swissartresearch.net/ontology/rds#label>')
    parser.add_argument('--endpoint',required=True, help='SPARQL endpoint to use for querying and updating labels')
    parser.add_argument('--limit_graph', required=False, help='limit the update to a specific graph')
    parser.add_argument('--output_directory', required=False, default='/data/labels', help='directory to store output files')
    parser.add_argument('--page_size', required=False, type=int, default=3000000, help='number of results to fetch per query')
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--dataset", required=False, help="Dataset to update labels for (all datasets if not specified)")
    
    args = parser.parse_args()
    endpoint = args.endpoint
    output_directory = args.output_directory
    config = args.config
    dataset = args.dataset if args.dataset else None
    if args.limit_graph:
        limit_graph = args.limit_graph
    else:
        limit_graph = None
    page_size = args.page_size
    main(endpoint=endpoint, limit_graph=limit_graph, output_directory=output_directory, page_size=page_size, config=config, dataset=dataset)