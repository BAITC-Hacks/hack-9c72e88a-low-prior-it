"""Optional watcher: python -m wind_agent.worker --run-id RUN_ID --interval 60."""

import argparse
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description="Recompute a forecast when its stored inputs change")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args()
    if args.interval < 5:
        parser.error("interval must be at least 5 seconds")
    run_id = args.run_id
    with httpx.Client(base_url=args.api, timeout=60) as client:
        try:
            while True:
                try:
                    response = client.post(f"/api/v1/forecasts/{run_id}/refresh")
                    response.raise_for_status()
                    payload = response.json()
                    run_id = payload["run"]["id"]
                    print(f"changed={payload['changed']} run={run_id}", flush=True)
                except httpx.HTTPError as exc:
                    print(f"Refresh failed: {exc}", flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
