import argparse
import json
from pathlib import Path
from lib.utils import load_config

def generateFrontendConfiguration(*, config: str, datasets: str, output_app: str, namespace: str = "https://static.swissartresearch.net/partial/") -> None:
    """
    Generate the templates and configuration files for the frontend based on the provided YAML configuration.

    Args:
        config (str): Path to the YAML configuration file.
        datasets (str): Comma-separated list of active datasets. If not provided, all configured datasets will be used.
        output_app (str): Path to the app to write the configuration to.
    """
    config_path = Path(config)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config}")
    config_data = load_config(config_path)

    configuration = generateDatasetJSON(config_data, datasets)

    writeJSONconfiguration(configuration, output_app)
    writeValueDatasetLabels(config_data, configuration["datasets"], output_app, namespace)
    writeValueTypeLabels(config_data, configuration["types"], output_app, namespace)
    
def generateDatasetJSON(config, datasets = None):
    if datasets:
        active_datasets = set(datasets.split(","))
        filtered_datasets = {k: v for k, v in config['datasets'].items() if k in active_datasets}
    else:
        filtered_datasets = config['datasets']

    datasets_configuration = {}
    types_available = []

    for key, info in filtered_datasets.items():
        datasets_configuration[key] = {
            "name": info.get("name", key)
        }
        if "description" in info:
            datasets_configuration[key]["description"] = info["description"]
        if "types" in info:
            types_available.extend(info["types"].keys())
    types_available = sorted(set(types_available))

    configuration = {
        "datasets": datasets_configuration,
        "types": types_available
    }
    return configuration

def writeJSONconfiguration(configuration, output_app):
    output_path = Path(output_app) / "assets" / "no_auth" / "config" / "datasets.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(configuration, f, indent=4)

def writeValueDatasetLabels(config, datasets_available, output_app, namespace):
    namespace_urlencoded = namespace.replace(":", "%3A").replace("/", "%2F")
    filename = f"{namespace_urlencoded}valuesDatasetLabels.html"
    valueSet = ""
    for dataset_id in datasets_available:
        if dataset_id in config.get("datasets", {}):
            dataset_label = config["datasets"][dataset_id].get("name", dataset_id)
            try:
                dataset_prefix = config["datasets"][dataset_id]["namespace"]
            except KeyError:
                raise KeyError(f"Missing 'namespace' for dataset '{dataset_id}' in configuration.")
            valueSet += f'("{dataset_id}", "{dataset_label}", "{dataset_prefix}")\n'
    valuesClause = f"""
        VALUES (?dataset ?datasetLabel ?datasetPrefix) {{
            {valueSet}
        }}
    """

    output_path = Path(output_app) / "data" / "templates" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(valuesClause)

def writeValueTypeLabels(config, types_available, output_app, namespace):
    namespace_urlencoded = namespace.replace(":", "%3A").replace("/", "%2F")
    filename = f"{namespace_urlencoded}valueTypeLabels.html"
    valueSet = ""
    for type_id in types_available:
        if type_id in config.get("types", {}):
            type_label = config["types"][type_id].get("name", type_id)
            valueSet += f'("{type_id}", "{type_label}")\n'
    valuesClause = f"""
        VALUES (?type ?typeLabel) {{
            {valueSet}
        }}
    """

    output_path = Path(output_app) / "data" / "templates" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(valuesClause)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate frontend dataset and type configuration")
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--datasets", required=False, help="Comma-separated list of active datasets. Defaults to all configured datasets.")
    parser.add_argument("--output-app", required=True, help="Path to the app to write the configuration to.")
    parser.add_argument("--namespace", required=False, default="https://static.swissartresearch.net/partial/", help="Namespace for the frontend templates.")

    args = parser.parse_args()

    generateFrontendConfiguration(config=args.config, datasets=args.datasets, output_app=args.output_app, namespace=args.namespace)
