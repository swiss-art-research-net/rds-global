import os
import argparse
import json
from SPARQLWrapper import SPARQLWrapper, POST, URLENCODED

def main(predicate_file, endpoint, limit_graph=None):
    with open('/pipeline/tmp/responses/label_count_by_graph.json', 'r') as f:
        count_json = json.load(f)
    with open(predicate_file, 'r') as f:
        predicates = json.load(f)

    # if limit_graph is set, remove all keys from predicate apart from the specified graph
    if limit_graph:
        for graph in predicates.keys():
            if graph != limit_graph:
                predicates[graph] = []
        
    file_num = 0
    graph2nb = {count_json['results']['bindings'][i]['graph_name']['value'] : int(count_json['results']['bindings'][i]['count']['value']) for i in range(len(count_json['results']['bindings']))}

    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat('json')
    sparql.setMethod(POST)
    for graph, nb in graph2nb.items():
        if graph in predicates and len(predicates[graph]):
            counter = 0
            # check if predicates[graph] is a list or a string
            if type(predicates[graph]) == list:
                predicatesPath = ' | '.join(predicates[graph])
                predicatesQuery = '?subject ' + predicatesPath + ' ?value .'
            elif type(predicates[graph]) == str:
                predicatesQuery = predicates[graph]
            while counter <= nb:
                query = """
                SELECT ?subject ?value WHERE {{
                    GRAPH <{0}> {{
                        {1}
                    }}
                }} ORDER BY DESC(?subject) OFFSET {2} LIMIT 3000000
                """.format(graph, predicatesQuery, str(counter))
                counter = counter + 3000000

                sparql.setQuery(query)
                results = sparql.query().convert()
                nquadLines = []
                for result in results["results"]["bindings"]:
                    subject = result["subject"]["value"]
                    value = result["value"]["value"]
                    subjectStr = f"<{subject}>" if result["subject"]["type"] == "uri" else f"\"{subject}\""
                    valueStr = f"\"{value}\""
                    # Add datatype or language if present
                    if "xml:lang" in result["value"]:
                        valueStr += f"@{result['value']['xml:lang']}"
                    elif "datatype" in result["value"]:
                        valueStr += f"^^<{result['value']['datatype']}>"
                    predicateStr = "<http://schema.swissartresearch.net/ontology/rds#label>"
                    graphStr = f"<http://schema.swissartresearch.net/rds/labels>"
                    nquadLine = f"{subjectStr} {predicateStr} {valueStr} {graphStr} .\n"
                    nquadLines.append(nquadLine)

                out_path = f"/pipeline/tmp/labels_{file_num}.nq"
                with open(out_path, "w") as out_f:
                    out_f.writelines(nquadLines)

                file_num = file_num + 1
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    parser = argparse.ArgumentParser(description = 'Produce ttl files with entities and their labels using a unified RDS predicate <http://schema.swissartresearch.net/ontology/rds#label>')
    parser.add_argument('--predicate_file', required=True,help='file with predicate to use to query for entity labels')
    parser.add_argument('--endpoint',required=True, help='SPARQL endpoint to use for querying and updating labels')
    parser.add_argument('--limit_graph', required=False, help='limit the update to a specific graph')
    
    args = parser.parse_args()
    predicate_file = args.predicate_file
    endpoint = args.endpoint
    if args.limit_graph:
        limit_graph = args.limit_graph
    else:
        limit_graph = None
    
    main(predicate_file, endpoint, limit_graph)
