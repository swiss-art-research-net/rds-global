#!/usr/bin/env python3
import argparse
from html import parser
import subprocess
import sys
from pathlib import Path
import requests
import base64
import hashlib
import re
import json
from lib.utils import load_config


def run(cmd: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


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

    # only used if source-type == github_zip
    parser.add_argument("--github-username")
    parser.add_argument("--github-token")

    args = parser.parse_args()
    
    config = load_config(args.config)

    try:
        dataset_config = config["datasets"][args.dataset]
    except KeyError:
        raise RuntimeError(f"Dataset '{args.dataset}' not found in config")
    
    data_dir = Path(dataset_config["data_directory"])
    source = dataset_config["source"]

    source_type = source["type"]
    source_url = source.get("url")
    file_format = dataset_config.get("file_format", "nt")
    gunzip = str(dataset_config.get("gunzip", False)).lower() == "true"

    github_repo = source.get("repository")
    github_path = source.get("path")
    ontology_url = dataset_config.get("ontology", {}).get("url")

    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{args.dataset}] Updating dataset: {data_dir}")
    print(f"Source type: {source_type}")

    if source_type in ("http_file", "http_zip"):
        if not source_url:
            raise RuntimeError("source-url is required for HTTP sources")

        if source_type == "http_zip":
            archive = data_dir / "data.zip"
            download_http(source_url, archive)
            run(["unzip", "-o", archive.name], cwd=data_dir)
        else:
            out_file = data_dir / f"data.{file_format}"
            if gunzip:
                gz = out_file.with_suffix(out_file.suffix + ".gz")
                download_http(source_url, gz)
                run(["gunzip", "-f", gz.name], cwd=data_dir)
            else:
                download_http(source_url, out_file)

    elif source_type == "github_zip":
        if not all([args.github_username, args.github_token, github_repo, github_path]):
            raise RuntimeError("GitHub repository, path, username and token are required")

        archive = data_dir / "data.zip"

        download_github_file(
            username=args.github_username,
            token=args.github_token,
            repo=github_repo,
            path=github_path,
            out_path=archive,
        )

        run(["unzip", "-o", archive.name], cwd=data_dir)
        archive.unlink()

    else:
        raise ValueError(f"Unsupported source type: {source_type}")
    
    if args.dataset == "geonames":
        nt_file = data_dir / "geonames.nt"
        if not nt_file.exists():
            print("[geonames] Converting to NTriples")
            script_src = Path("/pipeline/scripts/convert2ntriples.py")
            script_dst = data_dir / "convert2ntriples.py"
            script_dst.write_bytes(script_src.read_bytes())
            run(["python", script_dst.name], cwd=data_dir)
            script_dst.unlink()
        else:
            print("[geonames] NTriples already exist — skipping conversion")

    
    if args.dataset == "gnd" and ontology_url:
        print(f"[gnd] Downloading ontology from {ontology_url}")
        ttl_path = data_dir / "gnd-ontology.ttl"
        nt_path = data_dir / "gnd-ontology.nt"

        download_http(ontology_url, ttl_path)
        run(["rapper", "-i", "turtle", "-o", "ntriples", ttl_path.name], cwd=data_dir)

        ttl_path.unlink()


    print(f"[{args.dataset}] Download completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
