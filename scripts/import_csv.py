"""Import canonical observations, without guessing timestamp or unit semantics."""
import argparse
import csv
from pathlib import Path

import httpx

from wind_contracts import DatasetImport, Observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--provenance", default="Canonical CSV imported by repository helper; see source file metadata")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()
    with args.file.open(encoding="utf-8-sig", newline="") as stream:
        observations = [Observation.model_validate(row) for row in csv.DictReader(stream)]
    body = DatasetImport(name=args.name, demo=args.demo, provenance=args.provenance, observations=observations)
    response = httpx.post(f"{args.api}/datasets", json=body.model_dump(mode="json"), timeout=120)
    response.raise_for_status()
    print(response.json()["id"])


if __name__ == "__main__":
    main()
