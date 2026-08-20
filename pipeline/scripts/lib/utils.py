import yaml

RDS_GRAPH_NAMESPACE = "http://schema.swissartresearch.net/rds/graph/"
RDS_ONTOLOGY_NAMESPACE = "http://schema.swissartresearch.net/ontology/rds#"

def generate_prefixes_for_SPARQL(prefixes):
    items = sorted(prefixes.items(), key=lambda kv: kv[0])
    return "\n".join([f"PREFIX {p}: <{uri}>" for p, uri in items])

def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
    
def sanitise_string_value_for_turtle(value):
    value_str = value.replace('\\', '\\\\')
    value_str = value_str.replace('"', '\\"')
    value_str = f"\"{value_str}\""
    return value_str