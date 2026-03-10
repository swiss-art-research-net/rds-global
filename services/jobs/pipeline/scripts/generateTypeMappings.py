import argparse

from SPARQLWrapper import SPARQLWrapper, POST, JSON
from lib.utils import load_config, generate_prefixes_for_SPARQL as generate_prefixes, RDS_GRAPH_NAMESPACE, RDS_ONTOLOGY_NAMESPACE

PAGE_SIZE = 3000000
TYPES_GRAPH = f"<{RDS_GRAPH_NAMESPACE}types>"
TYPE_PREDICATE = f"<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
DEFAULT_TYPE_QUERY = "?subject a ?value ."

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
        prefixesForQuery = generate_prefixes(prefixes)
        types = dataset.get("types")
        typeQuery = dataset.get("queries", {}).get("types", DEFAULT_TYPE_QUERY).replace("?value", "?type")
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
                            {typeQuery}
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
                    nquad_lines.append(f"{subject} {TYPE_PREDICATE} <{RDS_ONTOLOGY_NAMESPACE}{typeToMap}> {TYPES_GRAPH} .\n")
                out_path = f"{output_directory}/types_{dataset_id}_{file_num}.nq"
                with open(out_path, "w") as out_f:
                    out_f.writelines(nquad_lines)
                file_num = file_num + 1
                # debug
                hasResults = False
    
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