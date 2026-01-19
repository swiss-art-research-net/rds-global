import os
import argparse
import json

from SPARQLWrapper import SPARQLWrapper, POST, JSON

LABEL_PREDICATE = "<http://schema.swissartresearch.net/ontology/rds#label>"
LABEL_GRAPH = "<http://schema.swissartresearch.net/rds/labels>"
PAGE_SIZE = 3000000

def main(*, predicate_file, endpoint, output_directory, limit_graph=None, page_size=PAGE_SIZE):
    
    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)

    count_query = """
        SELECT ?graph_name ( COUNT ( * ) AS ?count ) WHERE { 
            GRAPH ?graph_name { ?s ?p ?o . } 
        } GROUP BY ?graph_name
    """
    sparql.setQuery(count_query)
    count_json = sparql.query().convert()
    namedGraphsAndNumBindings = {count_json['results']['bindings'][i]['graph_name']['value'] : int(count_json['results']['bindings'][i]['count']['value']) for i in range(len(count_json['results']['bindings']))}

    with open(predicate_file, 'r') as f:
        predicates = json.load(f)

    # if limit_graph is set, remove all keys from predicate apart from the specified graph
    if limit_graph:
        for graph in predicates.keys():
            if graph != limit_graph:
                predicates[graph] = []
        
    file_num = 0

    for graph, nb in namedGraphsAndNumBindings.items():
        if graph in predicates and len(predicates[graph]):
            counter = 0
            # check if predicates[graph] is a list or a string
            if type(predicates[graph]) == list:
                predicates_path = ' | '.join(predicates[graph])
                predicates_query = '?subject ' + predicates_path + ' ?value .'
            elif type(predicates[graph]) == str:
                predicates_query = predicates[graph]
            while counter <= nb:
                query = """
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
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    parser = argparse.ArgumentParser(description = 'Produce ttl files with entities and their labels using a unified RDS predicate <http://schema.swissartresearch.net/ontology/rds#label>')
    parser.add_argument('--predicate_file', required=True,help='file with predicate to use to query for entity labels')
    parser.add_argument('--endpoint',required=True, help='SPARQL endpoint to use for querying and updating labels')
    parser.add_argument('--limit_graph', required=False, help='limit the update to a specific graph')
    parser.add_argument('--output_directory', required=False, default='/data/labels', help='directory to store output files')
    parser.add_argument('--page_size', required=False, type=int, default=3000000, help='number of results to fetch per query')
    
    args = parser.parse_args()
    predicate_file = args.predicate_file
    endpoint = args.endpoint
    output_directory = args.output_directory
    if args.limit_graph:
        limit_graph = args.limit_graph
    else:
        limit_graph = None
    page_size = args.page_size
    main(predicate_file=predicate_file, endpoint=endpoint, limit_graph=limit_graph, output_directory=output_directory, page_size=page_size)