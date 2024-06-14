#!/bin/bash

################################################################################
# Help                                                                         #
################################################################################
Help()
{
   # Display Help
   echo "Perform label service workaround by adding labels to entities through the predicate "
   echo
   echo "Syntax: adjustLabels.sh -b <blazegraph_journal> -p <predicates> [-g <graphs>]"
   echo "<blazegraph_journal>	Path to blazegraph journal file"
   echo "<predicates>		Path to text file with predicates to use, they have to be ready to inset in a SPARQL query (see all_predicated.txt for example)"
   echo "options:"
   echo "g     			Graphs to query, they have to be in a format that is ready to insert in a SPARQL query (see graphs.txt for example)"
   echo
}

while getopts 'hg:p:b:' flag; do
   case "${flag}" in
      h) # display Help
         Help
         exit;;
      g) graphs=$(<${OPTARG});;
      p) predicates=$(<${OPTARG});;
      b) blazegraph=$OPTARG;;
   esac
done

if [ ! "$blazegraph" ] || [ ! "$predicates" ]
then
    Help
    exit 1
fi

#set up folders and blazegraph runner
mkdir requests
mkdir responses
cd ../utils/blazegraph-runner
sbt stage
cd ../../labelAdjustment
#get number of triples for labels
#echo "SELECT (COUNT(*) AS ?count) WHERE { ?entity $predicates  ?ext . }" > requests/label_count.rq

if [[ -z $graphs ]]
then
	echo "SELECT ?graph_name
       ( COUNT ( * ) AS ?count )
	WHERE
  	{
    	GRAPH ?graph_name
      	{
		?subject $predicates ?label .
	      }
  	}
	GROUP BY ?graph_name" > requests/label_count_by_graph.rq
else
	echo "Using graph option"
	echo "SELECT ?graph_name ( COUNT ( * ) AS ?count )
        WHERE
        {
	VALUES (?graph_name) {
    	$graphs
	}	
        GRAPH ?graph_name
        {
                ?subject $predicates ?label .
              }
        }
        GROUP BY ?graph_name" > requests/label_count_by_graph.rq
fi

../utils/blazegraph-runner/target/universal/stage/bin/blazegraph-runner select --journal=$3 --outformat=json requests/label_count_by_graph.rq  "responses/label_count_by_graph.json"

#USE THIS TO MATERIALIZE TTL FILES
#mkdir output
#python get_label_ttl_files.py --predicate_file $4 --blazegraph_journal $3
#../utils/blazegraph-runner/target/universal/stage/bin/blazegraph-runner load --journal=$3 --graph="http://schema.swissartresearch.net/rds/labels" --informat=turtle output/*.ttl


#USE THIS TO INSERT LABELS DIRECTLY IN JOURNAL FILE (NO TTL FILES WILL BE GENERATED)
python update_labels.py --predicate_file $4 --blazegraph_journal $3


#SCRAP
#label_count=$(jq -r '.results.bindings[0].count.value' label_count.json)
#echo "SELECT * WHERE { ?entity $predicates  ?ext . }" > ../../labels.rq
#./target/universal/stage/bin/blazegraph-runner select --journal=$1 --outformat=tsv same_as.rq  "../../labels.tsv"
#awk 'BEGIN{ FS = OFS = "\t" } { $1 = $1 FS "<http://schema.swissartresearch.net/ontology/rds#label>" }1' ../../labels.tsv > ../../labels.tsv 
