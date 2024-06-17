#!/bin/bash

mkdir -p ./data

if [ -z "${BLAZEGRAPH_ENDPOINT}" ]; then
    BLAZEGRAPH_ENDPOINT="http://localhost:8081/blazegraph/namespace/kb/sparql"
fi

if [ -z "${WIKIDATA_ENDPOINT}" ]; then
    WIKIDATA_ENDPOINT="https://query.wikidata.org/sparql"
fi

DOWNLOAD_ATTEMPTS_NUMBER=5
CONNECT_TIMEOUT=10
MAX_TIME=1200

function xfetchData() {
  local dataset="$1"
  echo >&2 "Skipped fetching of dataset $dataset: ignore"
}

function fetchData() {
  local dataset="$1"
  local endpoint="$2"
  local query="$3"
  local outputFile="$4"

  if [ -f "$outputFile" ]; then
    echo >&2 "Skipped fetching of dataset $dataset: file $outputFile already exists"
    return
  fi

  echo >&2 "Fetching dataset $dataset..."
  for ((i=1; i<=DOWNLOAD_ATTEMPTS_NUMBER; i++)) do
    if [[ ! -f $outputFile ]]; then
      echo "Try $i of $DOWNLOAD_ATTEMPTS_NUMBER"
      curl --location --connect-timeout $CONNECT_TIMEOUT --max-time $MAX_TIME --request POST "$endpoint" \
        --header 'Content-Type: application/x-www-form-urlencoded' \
        --header 'Accept: text/turtle' \
        --data-urlencode "query=$query" > "$outputFile"
      local rc=$?

      if [ $rc -ne 0 ]; then
        echo >&2 "Failed to fetch dataset $dataset: curl returned $rc"
        rm $outputFile
      fi
    fi
  done
  if [ $rc -ne 0 ]; then
    echo >&2 "Failed to fetch dataset $dataset: curl returned $rc"
    rm $outputFile
    return $rc
  fi
}


# AAT
fetchData "AAT" ${BLAZEGRAPH_ENDPOINT} 'PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  GRAPH <http://vocab.getty.edu/aat/graph> {
    ?candidate2 (skos:exactMatch | skos:closeMatch) ?candidate1 .
  }
}' ./data/aatSameAs.ttl

# ULAN
fetchData "ULAN" ${BLAZEGRAPH_ENDPOINT} 'PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  GRAPH <http://vocab.getty.edu/ulan/graph> {
    ?candidate2 (skos:exactMatch | skos:closeMatch) ?candidate1 .
  }
}' ./data/ulanSameAs.ttl

# GND
fetchData "Gnd-1" ${BLAZEGRAPH_ENDPOINT} 'PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  {SELECT * WHERE {
      VALUES (?predicate) {
          (schema:sameAs)
          (rdfs:seeAlso)
          (skos:exactMatch)
      }
      GRAPH <https://d-nb.info/gnd/authorities/graph> {
      ?candidate2 ?predicate ?candidate1 .
      }
  } LIMIT 10397743}
}' ./data/gndSameAs_1.ttl

fetchData "Gnd-2" ${BLAZEGRAPH_ENDPOINT} 'PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  {SELECT * WHERE {
      VALUES (?predicate) {
          (schema:sameAs)
          (rdfs:seeAlso)
          (skos:exactMatch)
      }
      GRAPH <https://d-nb.info/gnd/authorities/graph> {
      ?candidate2 ?predicate ?candidate1 .
      }
  } OFFSET 10397743 LIMIT 10397750}
}' ./data/gndSameAs_2.ttl

# LOC
fetchData "LOC" ${BLAZEGRAPH_ENDPOINT} 'PREFIX loc: <http://www.loc.gov/mads/rdf/v1#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  GRAPH <http://vocab.getty.edu/loc/graph> {
    ?candidate2 loc:hasCloseExternalAuthority ?candidate1 .
  }
}' ./data/locSameAs.ttl

# BNF
fetchData "BNF" ${BLAZEGRAPH_ENDPOINT} 'PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  GRAPH <http://vocab.getty.edu/bnf/graph> {
    ?candidate2 (owl:sameAs | foaf:focus) ?candidate1 .
  }
}' ./data/bnfSameAs.ttl

# VIAF
fetchData "VIAF" ${BLAZEGRAPH_ENDPOINT} 'PREFIX schema: <http://schema.org/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  GRAPH <http://vocab.getty.edu/viaf/graph> {
    ?candidate2 schema:sameAs ?candidate1 .
  }
}' ./data/viafSameAs.ttl

# Thesaurus Objects Mobiliers
fetchData "thesobjmob" ${BLAZEGRAPH_ENDPOINT} 'PREFIX schema: <http://schema.org/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  GRAPH <http://data.culture.fr/thesaurus/resource/ark:/67717/T69/graph> {
    ?candidate2 skos:exactMatch ?candidate1 .
  }
}' ./data/thesobjmobSameAs.ttl

# Thesaurus Thésaurus de la désignation des œuvres architecturales et des espaces aménagés
fetchData "thesarchesp" ${BLAZEGRAPH_ENDPOINT} 'PREFIX schema: <http://schema.org/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
  GRAPH <http://data.culture.fr/thesaurus/resource/ark:/67717/T96/graph> {
    ?candidate2 skos:exactMatch ?candidate1 .
  }
}' ./data/thesarchespSameAs.ttl

# SIKART
fetchData "sikart" ${BLAZEGRAPH_ENDPOINT} 'PREFIX schema: <http://schema.org/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX crmdig: <http://www.ics.forth.gr/isl/CRMdig/>
CONSTRUCT { ?candidate2 owl:sameAs ?candidate1 . } WHERE {
GRAPH <http://recherche.sik-isea.ch/graph> {
  ?candidate2 crmdig:L54_same_as ?candidate1 .
  }
}' ./data/sikartSameAs.ttl

# Wikidata
# ==============================================================

# Wikidata VIAF-1
# you can add ORDER BY ?candidate ?sameAsID - it should the right decision but
# in this case the queries never be completed
VIAF_PARTS_COUNT=14
VIAF_RESULTS_IN_PART=200000
if (( VIAF_PARTS_COUNT == 0 )); then
  fetchData "Wikidata VIAF" ${WIKIDATA_ENDPOINT} 'PREFIX owl: <http://www.w3.org/2002/07/owl#>
  PREFIX wdt: <http://www.wikidata.org/prop/direct/>
  CONSTRUCT {
      ?candidate owl:sameAs ?sameAs .
  } WHERE {
      {SELECT ?candidate ?sameAsID WHERE {
          ?candidate wdt:P214 ?sameAsID .
      }}
      FILTER (!(REGEX(?sameAsID, "[\", ]", "i")))
      BIND (IRI(CONCAT("http://viaf.org/viaf/", ?sameAsID)) as ?sameAs)
  }' ./data/wikidataSameAsVIAF.ttl
else
  for ((n=0; n<=VIAF_PARTS_COUNT; n++)) do
    OFFSET=$((n * VIAF_RESULTS_IN_PART))
    if (( n==0 )); then
      OFFSET_STR=""
    else
      OFFSET_STR=" OFFSET $OFFSET"
    fi
    echo "Fetching part $n of $VIAF_PARTS_COUNT"
    fetchData "Wikidata VIAF-${n}" ${WIKIDATA_ENDPOINT} "PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    CONSTRUCT {
        ?candidate owl:sameAs ?sameAs .
    } WHERE {
      {SELECT ?candidate ?sameAsID WHERE {
          ?candidate wdt:P214 ?sameAsID .
      }$OFFSET_STR LIMIT $VIAF_RESULTS_IN_PART}
      FILTER (!(REGEX(?sameAsID, \"[\\\", ]\", \"i\")))
      BIND (IRI(CONCAT(\"http://viaf.org/viaf/\", ?sameAsID)) as ?sameAs)
    }" ./data/wikidataSameAsVIAF-$n.ttl
  done
fi

# Wikidata GND
fetchData "Wikidata GND" ${WIKIDATA_ENDPOINT} 'PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
CONSTRUCT {
    ?candidate owl:sameAs ?sameAs .
} WHERE {
  ?candidate wdt:P227 ?sameAsID .
  FILTER (!(REGEX(?sameAsID, "[\", ]", "i")))
  BIND (IRI(CONCAT("https://d-nb.info/gnd/", ?sameAsID)) as ?sameAs)
}' ./data/wikidataGNDSameAs.ttl

# Wikidata BNF
fetchData "Wikidata BNF" ${WIKIDATA_ENDPOINT} 'PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
CONSTRUCT {
    ?candidate owl:sameAs ?sameAs .
} WHERE {
  ?candidate wdt:P268 ?sameAsID .
  FILTER (!(REGEX(?sameAsID, "[\", ]", "i")))
  BIND (IRI(CONCAT("http://data.bnf.fr/ark:/12148/", ?sameAsID)) as ?sameAs)
}' ./data/wikidataBNFSameAs.ttl

# Wikidata LOC
# you can add ORDER BY ?candidate ?sameAsID - it should the right decision but
# in this case the queries never be completed
echo "Wikidata LOC feetching..."
LOC_PARTS_COUNT=7
LOC_RESULTS_IN_PART=200000
if (( LOC_PARTS_COUNT == 0 )); then
  fetchData "Wikidata LOC" ${WIKIDATA_ENDPOINT} 'PREFIX owl: <http://www.w3.org/2002/07/owl#>
  PREFIX wdt: <http://www.wikidata.org/prop/direct/>
  CONSTRUCT {
      ?candidate owl:sameAs ?sameAs .
  } WHERE {
    ?candidate wdt:P244 ?sameAsID .
    FILTER (!(REGEX(?sameAsID, "[\", ]", "i")))
    BIND (IRI(CONCAT("http://id.loc.gov/authorities/names/", ?sameAsID)) as ?sameAs)
  }' ./data/wikidataLOCSameAs.ttl
else
  for ((n=0; n<=LOC_PARTS_COUNT; n++)) do
    OFFSET=$((n * LOC_RESULTS_IN_PART))
    if (( n==0 )); then
      OFFSET_STR=""
    else
      OFFSET_STR=" OFFSET $OFFSET"
    fi
    echo "Fetching part $n of $LOC_PARTS_COUNT"
    fetchData "Wikidata LOC-${n}" ${WIKIDATA_ENDPOINT} "PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    CONSTRUCT {
        ?candidate owl:sameAs ?sameAs .
    } WHERE {
      {SELECT ?candidate ?sameAsID WHERE {
        ?candidate wdt:P244 ?sameAsID .
      }$OFFSET_STR LIMIT $LOC_RESULTS_IN_PART}
      FILTER (!(REGEX(?sameAsID, \"[\\\", ]\", \"i\")))
      BIND (IRI(CONCAT(\"http://id.loc.gov/authorities/names/\", ?sameAsID)) as ?sameAs)
    }" ./data/wikidataLOCSameAs-${n}.ttl
  done
fi

# Wikidata ULAN
fetchData "Wikidata ULAN" ${WIKIDATA_ENDPOINT} 'PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
CONSTRUCT {
    ?candidate owl:sameAs ?sameAs .
} WHERE {
  ?candidate wdt:P245 ?sameAsID .
  FILTER (!(REGEX(?sameAsID, "[\", ]", "i")))
  BIND (IRI(CONCAT("http://vocab.getty.edu/ulan/", ?sameAsID)) as ?sameAs)
}' ./data/wikidataUlanSameAs.ttl

#Wikidata Sikart (persons)
fetchData "Wikidata Sikart" ${WIKIDATA_ENDPOINT} 'PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
CONSTRUCT {
    ?candidate owl:sameAs ?sameAs .
} WHERE {
  ?candidate wdt:P781 ?sameAsID .
  FILTER EXISTS {
    ?candidate wdt:P31 wd:Q5 .
  }
  FILTER (!(REGEX(?sameAsID, "[\", ]", "i"))) .
  BIND (IRI(CONCAT("https://recherche.sik-isea.ch/person-", ?sameAsID)) as ?sameAs) .
}' ./data/wikidataSikartSameAs.ttl
