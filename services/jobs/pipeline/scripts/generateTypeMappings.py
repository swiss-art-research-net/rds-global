import argparse
import yaml

from SPARQLWrapper import SPARQLWrapper, POST, JSON

PAGE_SIZE = 3000000
RDS_NAMESPACE = "http://schema.swissartresearch.net/ontology/rds#"
TYPES_GRAPH = "<http://schema.swissartresearch.net/rds/types>"

def generateTypeMappings(*, endpoint, output_directory, page_size=PAGE_SIZE, config, dataset=None):
    
    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)

    config = load_config(config)
    datasets = config.get("datasets", {})

    # if dataset is specified, limit to that dataset
    if dataset:
        if dataset in datasets:
            datasets = {dataset: datasets[dataset]}
        else:
            print(f"Dataset {dataset} not found in config")
            return
        
    for dataset_id, dataset in datasets.items():
        graph = dataset.get("graph")
        prefixes = dataset.get("prefixes", {})
        prefixes['rdf'] = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
        prefixesForQuery = _generate_prefixes(prefixes)
        types = dataset.get("types")
        file_num = 0
        for typeToMap, types in types.items(): 
            counter = 0
            hasResults = True
            typeValues = ' '.join([f"({t})" for t in types])
            while hasResults:
                offset = str(counter)
                limit = str(page_size)
                query = prefixesForQuery + f"""
                    SELECT ?subject WHERE {{
                        GRAPH <{graph}> {{
                            ?subject rdf:type ?type .
                            VALUES (?type) {{ 
                                {typeValues}
                            }}
                        }}
                    }} ORDER BY DESC(?subject) OFFSET {offset} LIMIT {limit}"""
                counter = counter + page_size
                sparql.setQuery(query)
                try:
                    results = sparql.query().convert()
                except Exception as e:
                    print(f"Error querying SPARQL endpoint: {e}")
                    print(f"Query: {query}")
                    return
                if (len(results["results"]["bindings"]) == 0):
                    hasResults = False
                    continue
                nquad_lines = []
                for result in results["results"]["bindings"]:
                    subject = f"<{result["subject"]["value"]}>"
                    nquad_lines.append(f"{subject} <http://schema.swissartresearch.net/ontology/rds#type> <{RDS_NAMESPACE}{typeToMap}> {TYPES_GRAPH} .\n")
                out_path = f"{output_directory}/types_{dataset_id}_{file_num}.nq"
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
    
    parser = argparse.ArgumentParser(description = 'Produce NQuad files with entities and their types using the unified RDS ontology')
    parser.add_argument('--endpoint',required=True, help='SPARQL endpoint to use for querying')
    parser.add_argument('--output-directory', required=False, default='/data/type-mappings', help='Directory to store output files')
    parser.add_argument('--page-size', required=False, type=int, default=3000000, help='Number of results to fetch per query')
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--dataset", required=False, help="Dataset to generate type mappings for (all datasets if not specified)")
    
    args = parser.parse_args()
    endpoint = args.endpoint
    output_directory = args.output_directory
    config = args.config
    dataset = args.dataset if args.dataset else None
 
    page_size = args.page_size
    generateTypeMappings(endpoint=endpoint, output_directory=output_directory, page_size=page_size, config=config, dataset=dataset)