#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path
import requests
import base64
import hashlib
import re
from lib.utils import load_config
import rdflib
import os


def run(cmd: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")

def download_data_from_query(query: str, endpoint: str, out_path: Path, page_size: int) -> None:
    page = 0
    offset = 0
    hasResults = True
    while hasResults:
        paged_query = f"{query}\nLIMIT {page_size} OFFSET {offset}"
        print(f"Downloading page {page} (offset {offset})...")
        headers = {}
        headers["Accept"] = "application/n-triples"
        response = requests.get(endpoint, params={"query": paged_query}, headers=headers)
        response.raise_for_status()
        if response.status_code != 200:
            raise RuntimeError(f"SPARQL query failed with status code {response.status_code}: {response.text}")

        page_file = out_path / f"data_page_{page}.nt"
        payload = response.text.strip()
        if not payload:
            hasResults = False
            print("No more results, finished downloading.")
            break
        with open(page_file, "w", encoding="utf-8") as f:
            f.write(payload)
            if not payload.endswith("\n"):
                f.write("\n")
    
        page += 1
        offset += page_size

def download_http(url: str, out_path: Path) -> None:
    run(["curl", "-fL", url, "-o", str(out_path)])


def download_github_file(*, username: str, token: str, repo: str, path: str, out_path: Path) -> None:
    
    folder, filename = path.rsplit("/", 1)
    folder_url = f"https://api.github.com/repos/{repo}/contents/{folder}"

    folder_req = requests.get(folder_url, auth=(username, token))
    folder_req.raise_for_status()
    folder_data = folder_req.json()

    try:
        requested_file = next(d for d in folder_data if d["name"] == filename)
    except StopIteration:
        raise RuntimeError(
            f"Could not find file {filename} in {folder_url}. "
            "Check path and access token."
        )

    if out_path.exists() and out_path.stat().st_size == requested_file["size"]:
        print("File already exists locally and file size matches", file=sys.stderr)
        return

    blob_url = f"https://api.github.com/repos/{repo}/git/blobs/{requested_file['sha']}"
    blob_req = requests.get(blob_url, auth=(username, token))
    blob_req.raise_for_status()

    blob_bytes = base64.b64decode(blob_req.json()["content"])

    # non lfs
    if b"https://git-lfs.github.com/spec/v1" not in blob_bytes:
        out_path.write_bytes(blob_bytes)
        print("Done!", file=sys.stderr)
        return

    # lfs
    pointer_text = blob_bytes.decode("utf-8", "ignore")
    sha = re.findall(r"sha256:([a-z0-9]+)", pointer_text)[0]
    size = int(re.findall(r"size ([0-9]+)", pointer_text)[0])

    if out_path.exists():
        local_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
        local_size = out_path.stat().st_size
        if sha == local_sha and size == local_size:
            print("File already exists locally and is up to date", file=sys.stderr)
            return

    lfs_url = f"https://github.com/{repo}.git/info/lfs/objects/batch"
    payload = {
        "operation": "download",
        "transfer": ["basic"],
        "objects": [{"oid": sha, "size": size}],
    }
    headers = {
        "Content-type": "application/json",
        "Accept": "application/vnd.git-lfs+json",
    }

    r = requests.post(
        lfs_url,
        json=payload,
        headers=headers,
        auth=(username, token),
    )
    r.raise_for_status()

    download_url = r.json()["objects"][0]["actions"]["download"]["href"]
    response = requests.get(download_url)
    response.raise_for_status()

    out_path.write_bytes(response.content)
    print("Done!", file=sys.stderr)



def main():

    parser = argparse.ArgumentParser(description="Download and prepare RDF datasets")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--data_directory", required=False)
    parser.add_argument("--github-username")
    parser.add_argument("--github-token")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.data_directory:
        data_dir = Path(args.data_directory)
    else:
        directory_source_data = Path(
            os.environ.get("DIRECTORY_SOURCE_DATA", "/data/source")
        )
        data_dir = directory_source_data / f"{args.dataset}-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    dataset_config = config["datasets"][args.dataset]
    if "source" not in dataset_config:
        raise RuntimeError(f"No source defined for dataset {args.dataset}")

    sources = dataset_config["source"]
    if not isinstance(sources, list):
        sources = [sources]

    print(f"[{args.dataset}] Updating dataset: {data_dir}")
    for idx, source in enumerate(sources):
        source_type = source.get("type", "http_zip")
        source_url = source.get("url")
        process_steps = source.get("process", [])
        github_repo = source.get("repository")
        github_path = source.get("path")
        file_format = source.get("file_format", "nt")

        # Download step
        if source_type in ("http_file", "http_zip"):
            if not source_url:
                raise RuntimeError("source-url is required for HTTP sources")
            if source_type == "http_zip":
                archive = data_dir / f"data_{idx}.zip"
                download_http(source_url, archive)
                input_file = archive
            else:
                out_file = data_dir / f"data_{idx}.{file_format}"
                if any(p == "gunzip" for p in process_steps):
                    gz = out_file.with_suffix(out_file.suffix + ".gz")
                    download_http(source_url, gz)
                    input_file = gz
                else:
                    download_http(source_url, out_file)
                    input_file = out_file
        elif source_type == "github_zip":
            if not all([args.github_username, args.github_token, github_repo, github_path]):
                raise RuntimeError("GitHub repository, path, username and token are required")
            archive = data_dir / f"data_{idx}.zip"
            download_github_file(
                username=args.github_username,
                token=args.github_token,
                repo=github_repo,
                path=github_path,
                out_path=archive,
            )
            input_file = archive
        elif source_type == "construct_query":
            if not source.get("query"):
                raise RuntimeError("Query is required for construct_query sources")
            if not source.get("endpoint"):
                raise RuntimeError("SPARQL endpoint is required for construct_query sources")
            # Rewrite prefixes which are sotred as {'wd': 'http://wikidata.org/entity/', 'wdt': 'http://wikidata.org/prop/direct/', 'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdfs': 'http://www.w3.org/2000/01/rdf-schema#', 'schema': 'http://schema.org/', 'skos': 'http://www.w3.org/2004/02/skos/core#'}
            prefixes = "\n".join(f"PREFIX {p}: <{iri}>" for p, iri in dataset_config.get("prefixes", {}).items())
            query = prefixes + "\n" + source["query"]
            print(query)
            page_size = source.get("page_size", 1000)
            download_data_from_query(query=query, endpoint=source["endpoint"], out_path=data_dir, page_size=page_size)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        # Process steps
        for step in process_steps:
            match step:
                case "unzip":
                    run(["unzip", "-o", input_file.name], cwd=data_dir)
                    input_file = None
                case "gunzip":
                    run(["gunzip", "-f", input_file.name], cwd=data_dir)
                    input_file = None
                case "rdfxml2nt":
                    # convert all .rdf files in the directory
                    for rdf_file in data_dir.glob("*.rdf"):
                        nt_file = rdf_file.with_suffix(".nt")
                        g = rdflib.Graph()
                        g.parse(str(rdf_file), format="xml")
                        g.serialize(destination=str(nt_file), format="nt")
                        print(f"Converted {rdf_file} to {nt_file}")
                    # convert any .txt files line by line as RDF/XML
                    for txt_file in data_dir.glob("*.txt"):
                        nt_file = txt_file.with_suffix(".nt")
                        with open(nt_file, "w") as fo:
                            totalStmt = 0
                            with open(txt_file, encoding="utf8") as fileobject:
                                count = 0
                                for line in fileobject:
                                    if count/10000 == int(count/10000):
                                        print(count)
                                    if count%2 != 0:
                                        g = rdflib.Graph()
                                        try:
                                            g.parse(data=line, format='xml')
                                            totalStmt += len(g)
                                            s = g.serialize(format='nt')
                                            fo.write(s)
                                        except Exception as e:
                                            print(f"Error parsing line {count} in {txt_file.name}: {e}")
                                    count += 1
                            print(f"Total statements from {txt_file.name}: {totalStmt}")
                case "ttl2nt":
                    # convert all ttl files to nt, but already handled in _prepareForIndexing
                    for ttl_file in data_dir.glob("*.ttl"):
                        nt_file = ttl_file.with_suffix(".nt")
                        g = rdflib.Graph()
                        g.parse(str(ttl_file), format="turtle")
                        g.serialize(destination=str(nt_file), format="nt")
                        print(f"Converted {ttl_file} to {nt_file}")
                case _:
                    print(f"Unknown process step: {step}")

    print(f"[{args.dataset}] Download and processing completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
