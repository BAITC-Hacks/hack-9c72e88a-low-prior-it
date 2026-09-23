"""Convert the canonical CSV contract to the dataset API; no timezone guessing."""

import argparse
import csv

import httpx
from wind_contracts.models import DatasetUpload, Observation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--name", required=True)
    parser.add_argument("--provenance", default="", help="Source and preparation assumptions")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Mark artificial training data and resulting models as demo",
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with open(args.file, encoding="utf-8-sig", newline="") as file:
        rows = [Observation.model_validate(row) for row in csv.DictReader(file)]
    payload = DatasetUpload(
        name=args.name, is_demo=args.demo, provenance=args.provenance, observations=rows
    )
    response = httpx.post(
        f"{args.api}/api/v1/datasets", json=payload.model_dump(mode="json"), timeout=60
    )
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
