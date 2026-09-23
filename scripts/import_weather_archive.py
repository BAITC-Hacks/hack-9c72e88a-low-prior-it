"""Import bundled 00 UTC ECMWF candidates or an explicit schedule-assumed reconstruction."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from wind_agent.ecmwf_archive import DEFAULT_ARCHIVE_PATH, import_ecmwf_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_ARCHIVE_PATH)
    parser.add_argument("--start", default="2024-03-14")
    parser.add_argument("--end", default="2026-03-01", help="Exclusive UTC initialization date")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument(
        "--output", type=Path, help="Write JSON locally instead of importing via API"
    )
    parser.add_argument(
        "--accept-schedule-assumption",
        action="store_true",
        help="Accept documented hindcast reconstruction with assumed +10h availability; "
        "does not establish historical operational publication proof",
    )
    args = parser.parse_args()
    imported = import_ecmwf_archive(
        args.input,
        start=datetime.combine(datetime.fromisoformat(args.start).date(), datetime.min.time(), UTC),
        end=datetime.combine(datetime.fromisoformat(args.end).date(), datetime.min.time(), UTC),
        accept_schedule_assumption=args.accept_schedule_assumption,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "metadata": imported.metadata,
                    "snapshots": [
                        snapshot.model_dump(mode="json") for snapshot in imported.snapshots
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {len(imported.snapshots)} snapshots to {args.output}")
    else:
        count = 0
        with httpx.Client(timeout=60) as client:
            for snapshot in imported.snapshots:
                response = client.post(
                    f"{args.api}/weather/snapshots", json=snapshot.model_dump(mode="json")
                )
                if response.status_code == 409:
                    # IDs include source checksum and assumption mode. The API keeps
                    # stored snapshots immutable; reruns never overwrite old imports.
                    continue
                response.raise_for_status()
                count += 1
        print(f"Imported {count} new snapshots; existing immutable IDs were retained.")
    print(json.dumps(imported.metadata, indent=2))
    if args.accept_schedule_assumption:
        print("HINDCAST / SCHEDULE ASSUMPTION: not proof of past operational availability.")
    else:
        print("UNVERIFIED candidates cannot be used in archive replay.")


if __name__ == "__main__":
    main()
