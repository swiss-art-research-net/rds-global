# Label Adjustment

In order to execute the label adjustment pipeline -
1. Create a text file containing one line with the predicate that attaches entities to their labels (this should be in SPARQL format and hence it can include multiple predicates through the use of `|` and/or `/`.
1. Change the file `adjustLabels.sh` depending on whether `ttl` files should be materialized.
1. Execute `adjustLabels.sh` in the following way -
```
adjustLabels.sh -b <blazegraph_journal> -p <predicates> [-g <graphs>]
```
such that -
* `<blazegraph_journal>` is the path to blazegraph journal file
* `<predicates>` is the path to text file with predicates to use, they have to be ready to inset in a SPARQL query (see all\_predicated.txt for example)
* `<graphs> are the graphs to query, they have to be in a format that is ready to insert in a SPARQL query (see graphs.txt for example)
For instance, it can be executed by running -
```
adjustLabels.sh -b ../blazegraph-data/blazegraph.jnl -p predicates.txt -g graphs.txt
```
