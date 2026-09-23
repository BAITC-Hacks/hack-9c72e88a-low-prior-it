"""Poll eligible input changes for one fixed issue time. Never advance replay time."""
import argparse
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("interval must be at least one second")
    with httpx.Client(timeout=60) as client:
        while True:
            try:
                response = client.post(f"{args.api}/forecasts/{args.run_id}/refresh")
                response.raise_for_status()
                args.run_id = response.json()["id"]
                print(args.run_id, response.json()["status"], flush=True)
            except httpx.HTTPError as exc:
                print(f"Refresh failed: {exc}", flush=True)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
