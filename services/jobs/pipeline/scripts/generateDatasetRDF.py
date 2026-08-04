import argparse
from pathlib import Path
from string import Template

import rdflib

from lib.utils import load_config, sanitise_string_value_for_turtle

PREFIXES_AND_CLASS_TEMPLATE = Template("""
@prefix aat: <http://vocab.getty.edu/aat/> .
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix crmdig: <http://www.ics.forth.gr/isl/CRMdig/> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rds: <http://schema.swissartresearch.net/ontology/rds#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix catalog: <https://platform.swissartresearch.net/catalog/> .
@prefix dataset: <https://platform.swissartresearch.net/dataset/> .
@prefix schema: <http://schema.org/> .

rds:Dataset a rdfs:Class ;
    rdfs:label "RDS Dataset" ;
    rdfs:comment "A dataset in the RDS platform." .

aat:300028543 a crm:E55_Type ;
    rdfs:label "Dataset" .

aat:300404670 a crm:E55_Type ;
    rdfs:label "preferred terms" .

aat:300404012 a crm:E55_Type ;
    rdfs:label "identifier" .

aat:300418049 a crm:E55_Type ;
    rdfs:label "brief description" .

aat:300435416 a crm:E55_Type ;
    rdfs:label "long description" .
""")

DATASET_TEMPLATE = Template("""
dataset:${dataset_id} a rds:Dataset , dcat:Dataset , crm:E73_Information_Object, crmdig:D1_Digital_Object ;
    rdfs:label ${dataset_name} ;
    dct:title ${dataset_name} ;
    dct:identifier ${dataset_identifier} ;
    dct:description ${dataset_description} ;
    dct:publisher ${publisher_reference} ;
    crm:P1_is_identified_by dataset:${dataset_id}-name, dataset:${dataset_id}-id ;
    crm:P94i_was_created_by dataset:${dataset_id}-creation ;
    crm:P2_has_type aat:300028543 ;
    crm:P67i_is_referred_to_by ${description_references} .

dataset:${dataset_id}-creation a crm:E65_Creation .

${publisher_block}

dataset:${dataset_id}-name a crm:E33_41_Linguistic_Appellation ;
    crm:P190_has_symbolic_content ${dataset_name} ;
    crm:P2_has_type aat:300404670 .

dataset:${dataset_id}-id a crm:E41_Identifier ;
    crm:P190_has_symbolic_content ${dataset_identifier} ;
    crm:P2_has_type aat:300404012 .

${brief_description_block}
${long_description_block}
""")

PUBLISHER_URI_TEMPLATE = Template("""
<${publisher_url}> a foaf:Organization, crm:E74_Group ;
    foaf:name ${publisher_name} ;
    crm:P1_is_identified_by <${publisher_url}/name> .

<${publisher_url}/name> a crm:E33_41_Linguistic_Appellation ;
    crm:P190_has_symbolic_content ${publisher_name} .

dataset:${dataset_id}-creation crm:P14_carried_out_by <${publisher_url}> .
""")

PUBLISHER_LOCAL_TEMPLATE = Template("""
dataset:${dataset_id}-publisher a foaf:Organization, crm:E74_Group ;
    foaf:name ${publisher_name} ;
    crm:P1_is_identified_by dataset:${dataset_id}-publisher-name .

dataset:${dataset_id}-publisher-name a crm:E33_41_Linguistic_Appellation ;
    crm:P190_has_symbolic_content ${publisher_name} .

dataset:${dataset_id}-creation crm:P14_carried_out_by dataset:${dataset_id}-publisher .
""")

BRIEF_DESCRIPTION_TEMPLATE = Template("""
dataset:${dataset_id}-brief-description a crm:E33_Linguistic_Object ;
    crm:P190_has_symbolic_content ${brief_description} ;
    crm:P2_has_type aat:300418049 .
""")

LONG_DESCRIPTION_TEMPLATE = Template("""
dataset:${dataset_id}-long-description a crm:E33_Linguistic_Object ;
    crm:P190_has_symbolic_content ${long_description} ;
    crm:P2_has_type aat:300435416 .
""")


def format_literal(value: str) -> str:
    return sanitise_string_value_for_turtle(value)


def get_descriptions(dataset_info: dict) -> tuple[str | None, str | None]:
    description = dataset_info.get("description")
    if isinstance(description, dict):
        return description.get("brief"), description.get("full")
    if isinstance(description, str):
        return description, None
    return None, None


def build_publisher(dataset_id: str, dataset_info: dict) -> tuple[str, str]:
    publisher = dataset_info.get("publisher") or {}
    publisher_name = publisher.get("name")
    publisher_url = publisher.get("url")

    if publisher_url and publisher_name:
        return (
            f"<{publisher_url}>",
            PUBLISHER_URI_TEMPLATE.substitute(
                dataset_id=dataset_id,
                publisher_url=publisher_url,
                publisher_name=format_literal(publisher_name),
            ),
        )

    if publisher_name:
        return (
            f"dataset:{dataset_id}-publisher",
            PUBLISHER_LOCAL_TEMPLATE.substitute(
                dataset_id=dataset_id,
                publisher_name=format_literal(publisher_name),
            ),
        )

    return '""', ""


def build_description_blocks(dataset_id: str, brief_description: str | None, long_description: str | None) -> tuple[str, str, str]:
    description_references = []
    brief_block = ""
    long_block = ""

    if brief_description:
        description_references.append(f"dataset:{dataset_id}-brief-description")
        brief_block = BRIEF_DESCRIPTION_TEMPLATE.substitute(
            dataset_id=dataset_id,
            brief_description=format_literal(brief_description),
        )

    if long_description and long_description != brief_description:
        description_references.append(f"dataset:{dataset_id}-long-description")
        long_block = LONG_DESCRIPTION_TEMPLATE.substitute(
            dataset_id=dataset_id,
            long_description=format_literal(long_description),
        )

    if not description_references:
        description_references.append(f"dataset:{dataset_id}-brief-description")
        brief_block = BRIEF_DESCRIPTION_TEMPLATE.substitute(
            dataset_id=dataset_id,
            brief_description=format_literal(""),
        )

    return ", ".join(description_references), brief_block, long_block


def build_dataset_turtle(dataset_id: str, dataset_info: dict) -> str:
    dataset_name = format_literal(dataset_info.get("name", dataset_id))
    dataset_identifier = format_literal(dataset_id)
    brief_description, long_description = get_descriptions(dataset_info)
    dataset_description = format_literal(brief_description or long_description or "")
    publisher_reference, publisher_block = build_publisher(dataset_id, dataset_info)
    description_references, brief_block, long_block = build_description_blocks(dataset_id, brief_description, long_description)

    return DATASET_TEMPLATE.substitute(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        dataset_identifier=dataset_identifier,
        dataset_description=dataset_description,
        publisher_reference=publisher_reference,
        description_references=description_references,
        publisher_block=publisher_block,
        brief_description_block=brief_block,
        long_description_block=long_block,
    )


def generate_dataset_rdf(*, config: str, output_file: str, datasets: str | None = None) -> None:
    """
    Generate dataset metadata RDF based on the provided YAML configuration.

    Args:
        config (str): Path to the YAML configuration file.
        output_file (str): Path to the RDF file to write.
        datasets (str | None): Comma-separated list of active datasets. If not provided, all configured datasets will be used.
    """
    config_data = load_config(config)
    configured_datasets = config_data.get("datasets", {})

    if datasets:
        active_datasets = {dataset_id.strip() for dataset_id in datasets.split(",") if dataset_id.strip()}
        configured_datasets = {
            dataset_id: dataset_info
            for dataset_id, dataset_info in configured_datasets.items()
            if dataset_id in active_datasets
        }

    turtle = PREFIXES_AND_CLASS_TEMPLATE.substitute()
    for dataset_id, dataset_info in configured_datasets.items():
        turtle += "\n" + build_dataset_turtle(dataset_id, dataset_info)

    graph = rdflib.Graph()
    graph.parse(data=turtle, format="turtle")

    serialized = graph.serialize(format="turtle")
    if isinstance(serialized, bytes):
        serialized = serialized.decode("utf-8")

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate dataset metadata RDF from the datasets configuration")
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--datasets", required=False, help="Comma-separated list of active datasets. Defaults to all configured datasets.")
    parser.add_argument("--output-file", required=True, help="Path to the RDF file to write")

    args = parser.parse_args()
    generate_dataset_rdf(config=args.config, output_file=args.output_file, datasets=args.datasets)
