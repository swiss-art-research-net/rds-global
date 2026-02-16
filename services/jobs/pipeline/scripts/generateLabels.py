import argparse

from SPARQLWrapper import SPARQLWrapper, POST, JSON
from lib.utils import RDS_ONTOLOGY_NAMESPACE, load_config, generate_prefixes_for_SPARQL as generate_prefixes, RDS_GRAPH_NAMESPACE, RDS_ONTOLOGY_NAMESPACE

LABEL_PREDICATE = f"<{RDS_ONTOLOGY_NAMESPACE}label>"
LABEL_GRAPH = f"<{RDS_GRAPH_NAMESPACE}labels>"
PAGE_SIZE = 3000000

def main(*, endpoint, output_directory, page_size=PAGE_SIZE, config=None, dataset=None):
    
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
                prefixes = generate_prefixes(datasets[dataset].get("prefixes", {}))
                query = prefixes + """
                SELECT ?subject ?value WHERE {{
                    GRAPH <{0}> {{
                        {1}
                    }}
                }} ORDER BY DESC(?subject) OFFSET {2} LIMIT {3}
                """.format(graph, predicates_query, str(counter), str(page_size))
                counter = counter + page_size

                sparql.setQuery(query)
                try:
                    results = sparql.query().convert()
                except Exception as e:
                    print(f"Error querying SPARQL endpoint: {e}")
                    print(f"Query: {query}")
                    return
                # if no results, continue to next graph
                if len(results["results"]["bindings"]) == 0:
                    hasResults = False
                    continue
                nquad_lines = []
                for result in results["results"]["bindings"]:
                    subject = result["subject"]["value"]
                    value = result["value"]["value"]
                    subject_str = f"<{subject}>" if result["subject"]["type"] == "uri" else f"\"{subject}\""
                    # Sanitise value string (e.g. escape \ and " characters) to ensure valid NQuads output
                    
                    value_str = value.replace('\\', '\\\\')
                    value_str = value_str.replace('"', '\\"')
                    value_str = f"\"{value_str}\""
                    # Add datatype or language if present
                    if "xml:lang" in result["value"]:
                        value_str += f"@{result['value']['xml:lang']}"
                    elif "datatype" in result["value"]:
                        value_str += f"^^<{result['value']['datatype']}>"
                    nquad_line = f"{subject_str} {LABEL_PREDICATE} {value_str} {LABEL_GRAPH} .\n"
                    nquad_lines.append(nquad_line)
                out_path = f"{output_directory}/labels_{dataset}_{file_num}.nq"
                with open(out_path, "w") as out_f:
                    out_f.writelines(nquad_lines)

                file_num = file_num + 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    parser = argparse.ArgumentParser(description = 'Produce NQuad files with entities and their labels using a unified RDS predicate <http://schema.swissartresearch.net/ontology/rds#label>')
    parser.add_argument('--endpoint',required=True, help='SPARQL endpoint to use for querying and updating labels')
    parser.add_argument('--output-directory', required=False, default='/data/labels', help='directory to store output files')
    parser.add_argument('--page-size', required=False, type=int, default=3000000, help='number of results to fetch per query')
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--dataset", required=False, help="Dataset to generate labels for (all datasets if not specified)")
    
    args = parser.parse_args()
    endpoint = args.endpoint
    output_directory = args.output_directory
    config = args.config
    dataset = args.dataset if args.dataset else None
 
    page_size = args.page_size
    main(endpoint=endpoint, output_directory=output_directory, page_size=page_size, config=config, dataset=dataset)