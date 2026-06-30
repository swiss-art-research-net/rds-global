import argparse
import json
from pathlib import Path
from lib.utils import load_config

def generateFrontendConfiguration(*, config: str, datasets: str, output_file: str):
    """
    Generate a JSON configuration file for the frontend based on the provided YAML configuration.

    Args:
        config (str): Path to the YAML configuration file.
        datasets (str): Comma-separated list of active datasets. If not provided, all configured datasets will be used.
        output_file (str): Path to the output JSON file.
    """
    config_path = Path(config)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config}")
    config_data = load_config(config_path)

    if datasets:
        active_datasets = set(datasets.split(","))
        filtered_datasets = {k: v for k, v in config_data['datasets'].items() if k in active_datasets}
    else:
        filtered_datasets = config_data['datasets']

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

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(configuration, f, indent=4)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate frontend dataset and type configuration")
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--datasets", required=False, help="Comma-separated list of active datasets. Defaults to all configured datasets.")
    parser.add_argument("--output-file", required=True, help="Path to the output JSON file")

    args = parser.parse_args()

    generateFrontendConfiguration(config=args.config, datasets=args.datasets, output_file=args.output_file)
