
## Example SPARQL Query for AAT DataSet

```sparql
  PREFIX gvp: <http://vocab.getty.edu/ontology#>
  PREFIX xl: <http://www.w3.org/2008/05/skos-xl#>
  SELECT ?subject ?prefLabel (GROUP_CONCAT(DISTINCT STR(?type);SEPARATOR="||") as ?types) (GROUP_CONCAT(?label;SEPARATOR="||") as ?labels) ?description (COUNT(?match) as ?numMatches) WHERE {
    GRAPH <http://vocab.getty.edu/aat/graph> {
      ?subject a gvp:Concept, ?type .
  	?subject gvp:prefLabelGVP/xl:literalForm ?prefLabel .
      ?subject (gvp:prefLabelGVP | xl:prefLabel | xl:altLabel)/xl:literalForm ?label .
      {
        ?subject gvp:parentStringAbbrev ?description .
      }
    }
    OPTIONAL {
      GRAPH <http://schema.swissartresearch.net/rds/exact-match-statements> {
  	?subject <http://schema.swissartresearch.net/ontology/rds#related> ?match .
  	}
    }
  }
  GROUP BY ?subject ?prefLabel ?description 
  ORDER BY ?subject 
  LIMIT 1000
  OFFSET 0
```

## Example OpenSearch Query with Relevance Scoring

```bash
 curl -s -X POST http://localhost:9200/rds-entities/_search \
   -H 'Content-Type: application/json' \
   -d '{
     "query": {
       "function_score": {
         "query": {
           "multi_match": {
             "query": "painting",
             "fields": ["prefLabel^3", "labels"]
           }
         },
         "field_value_factor": {
           "field": "relevance",
           "factor": 1.0,
           "modifier": "log1p",
           "missing": 0
         },
         "boost_mode": "sum"
       }
     }
   }' | jq .
```