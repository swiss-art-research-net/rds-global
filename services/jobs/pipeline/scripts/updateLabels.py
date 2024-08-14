import os
import argparse
import json

def main(predicate_file, blazegraph_journal, limit_graph=None):
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
    #print(graph2nb) 
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
                INSERT {{ GRAPH <http://schema.swissartresearch.net/rds/labels> {{
                    ?subject <http://schema.swissartresearch.net/ontology/rds#label> ?value . 
                }} 
                }} WHERE {{
                    {{
                        SELECT * {{
                            GRAPH <{0}> {{
                                        {1}
                                    }}
                                }} ORDER BY DESC(?subject) OFFSET {2} LIMIT 3000000
                    }}
                }}
                """.format(graph, predicatesQuery, str(counter))            
                counter = counter + 3000000
                with open('/pipeline/tmp/requests/label_query.rq', 'w') as f:
                    f.write(query)
                bash_command = '../utils/blazegraph-runner/bin/blazegraph-runner update --journal={0} /pipeline/tmp/requests/label_query.rq'.format(blazegraph_journal, file_num)
                os.system(bash_command)

                file_num = file_num + 1
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    parser = argparse.ArgumentParser(description = 'Produce ttl files with entities and their labels using a unified RDS predicate <http://schema.swissartresearch.net/ontology/rds#label>')
    parser.add_argument('--predicate_file', required=True,help='file with predicate to use to query for entity labels')
    parser.add_argument('--blazegraph_journal',required=True, help='path to blazegraph journal file')
    parser.add_argument('--limit_graph', required=False, help='limit the update to a specific graph')
    
    args = parser.parse_args()
    predicate_file = args.predicate_file
    blazegraph_journal = args.blazegraph_journal
    if args.limit_graph:
        limit_graph = args.limit_graph
    else:
        limit_graph = None
    
    main(predicate_file, blazegraph_journal, limit_graph)
