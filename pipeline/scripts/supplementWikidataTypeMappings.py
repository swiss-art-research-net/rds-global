import argparse
import re 
from SPARQLWrapper import SPARQLWrapper, POST, JSON

from lib.utils import RDS_ONTOLOGY_NAMESPACE
from lib.sparql_data_download import fetch_total_count

BASE_QUERY_TEMPLATE = """
    PREFIX rds: <{RDS_ONTOLOGY_NAMESPACE}>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    CONSTRUCT {{
        ?wikidataEntity a ?otherRdsType .
    }}
    WHERE {{
        GRAPH <{wikidata_graph}> {{
            ?wikidataEntity a ?wdType .
        }}
    FILTER NOT EXISTS {{
        GRAPH <{types_graph}> {{
            ?wikidataEntity a ?rdsType .
        }}
    }}
    GRAPH <{match_graph}> {{
        ?otherEntity rds:related ?wikidataEntity .
    }}
    GRAPH <{types_graph}> {{
        ?otherEntity a ?otherRdsType .
    }}
}}
"""

def supplementWikidataTypeMappings(*, endpoint, output_directory, types_graph, match_graph, wikidata_graph, page_size=5000):
    query = BASE_QUERY_TEMPLATE.format(
        RDS_ONTOLOGY_NAMESPACE=RDS_ONTOLOGY_NAMESPACE,
        wikidata_graph=wikidata_graph,
        types_graph=types_graph,
        match_graph=match_graph
    )
    count_query = re.sub(r'CONSTRUCT\s*\{[^}]*\}', 'SELECT (COUNT(*) as ?count)', query, flags=re.IGNORECASE | re.DOTALL)
    total_count = fetch_total_count(endpoint=endpoint, count_query=count_query)
    print(f"Total rows to supplement: {total_count}")

    counter = 0
    hasResults = True
    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)

    while hasResults:
        offset = str(counter)
        limit = str(page_size)
        paginated_query = query + f" ORDER BY ?wikidataEntity OFFSET {offset} LIMIT {limit}"
        print(f"Fetching rows {counter} to {counter + page_size}...")
        results = sparql.query(paginated_query).convert()
        if not results["results"]["bindings"]:
            hasResults = False
            print("No more results.")
            break
        output_file = f"{output_directory}/wikidata_type_mappings_{counter}_{counter + page_size}.nt"
        with open(output_file, "w", encoding="utf-8") as f:
            for result in results["results"]["bindings"]:
                sub = result["s"]["value"]
                pred = result["p"]["value"]
                obj = result["o"]["value"]
                f.write(f"<{sub}> <{pred}> <{obj}> .\n")
        counter += page_size


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate type mappings for datasets")
    parser.add_argument("--endpoint", required=True, help="SPARQL endpoint URL")
    parser.add_argument("--output-directory", required=True, help="Directory to save output files")
    parser.add_argument("--types-graph", required=False, default="http://schema.swissartresearch.net/rds/graph/types", help="Graph URI for types")
    parser.add_argument("--match-graph", required=False, default="http://schema.swissartresearch.net/rds/exact-match-statements", help="Graph URI for matches")
    parser.add_argument("--wikidata-graph", required=False, default="http://wikidata.org/graph", help="Graph URI for Wikidata")
    parser.add_argument("--page-size", type=int, default=5000, help="Number of results per page")
    args = parser.parse_args()

    endpoint = args.endpoint
    output_directory = args.output_directory
    types_graph = args.types_graph
    match_graph = args.match_graph
    wikidata_graph = args.wikidata_graph
    page_size = args.page_size
    if page_size <= 0:
        raise ValueError("Page size must be a positive integer")

    supplementWikidataTypeMappings(
        endpoint=endpoint,
        output_directory=output_directory,
        page_size=page_size,
        types_graph=types_graph,
        match_graph=match_graph,
        wikidata_graph=wikidata_graph
    )