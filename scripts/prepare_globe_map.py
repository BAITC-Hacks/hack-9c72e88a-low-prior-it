"""Build the small, pinned Natural Earth country layer used by Explore (stdlib only)."""

import argparse
import hashlib
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_COMMIT = "9380cca83db5f9aef52d5e762765100745f84b27"
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{SOURCE_COMMIT}/geojson/ne_110m_admin_0_countries.geojson"
)
SOURCE_SHA256 = "6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "frontend/public/geo/countries.geojson"


def relative_ring(ring, label_lng):
    """Measure longitudes around the country label, including across the dateline."""
    return [(label_lng + (point[0] - label_lng + 180) % 360 - 180, point[1]) for point in ring]


def contains(ring, lng, lat):
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


def ring_area(ring):
    area = abs(
        sum(
            ring[index - 1][0] * point[1] - point[0] * ring[index - 1][1]
            for index, point in enumerate(ring)
        )
    )
    mean_lat = sum(point[1] for point in ring) / len(ring)
    return area * math.cos(math.radians(mean_lat))


def camera_span(geometry, label_lat, label_lng, code):
    """Frame the labelled mainland rather than distant overseas territories."""
    if code == "AQ":
        return 170.0
    polygons = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    rings = [relative_ring(polygon[0], label_lng) for polygon in polygons]
    labelled = [ring for ring in rings if contains(ring, label_lng, label_lat)]
    main_ring = max(labelled or rings, key=ring_area)
    lat_span = max(point[1] for point in main_ring) - min(point[1] for point in main_ring)
    lng_span = max(point[0] for point in main_ring) - min(point[0] for point in main_ring)
    return round(
        max(5.0, min(170.0, max(lat_span, lng_span * math.cos(math.radians(label_lat))))), 3
    )


def rounded_coordinates(coordinates):
    if isinstance(coordinates[0], (float, int)):
        return [round(value, 3) for value in coordinates[:2]]
    return [rounded_coordinates(child) for child in coordinates]


def prepare(source):
    features = []
    seen_codes = set()
    for feature in source["features"]:
        props = feature["properties"]
        candidates = [props.get(key) for key in ("ISO_A2_EH", "ISO_A2", "ADM0_A3")]
        code = next(
            (value for value in candidates if value and value != "-99" and value not in seen_codes),
            None,
        )
        if not code:
            raise ValueError(f"No unique country code for {props.get('ADMIN')}")
        seen_codes.add(code)
        lat, lng = float(props["LABEL_Y"]), float(props["LABEL_X"])
        geometry = feature["geometry"]
        if geometry["type"] not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"Unexpected geometry for {code}: {geometry['type']}")
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "code": code,
                    "name": props.get("NAME_EN") or props["ADMIN"],
                    "lat": round(lat, 3),
                    "lng": round(lng, 3),
                    "span": camera_span(geometry, lat, lng, code),
                },
                "geometry": {
                    "type": geometry["type"],
                    "coordinates": rounded_coordinates(geometry["coordinates"]),
                },
            }
        )
    if len(features) != 177:
        raise ValueError(f"Expected 177 countries/territories, found {len(features)}")
    kazakhstan = next(feature for feature in features if feature["properties"]["code"] == "KZ")
    if kazakhstan["properties"]["name"] != "Kazakhstan":
        raise ValueError("Country code KZ must identify Kazakhstan")
    return {"type": "FeatureCollection", "features": features}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, help="Optional local copy of the exact pinned source"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.source:
        raw = args.source.read_bytes()
    else:
        request = Request(SOURCE_URL, headers={"User-Agent": "energy-explorer-map-build/1.0"})
        with urlopen(request, timeout=60) as response:
            raw = response.read()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != SOURCE_SHA256:
        raise ValueError(f"Source checksum mismatch: expected {SOURCE_SHA256}, got {actual_sha}")
    prepared = prepare(json.loads(raw))
    output = (json.dumps(prepared, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(output) > 500_000:
        raise ValueError(f"Country layer exceeds the 500 KB size budget: {len(output)} bytes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(f"Wrote {len(prepared['features'])} countries/territories to {args.output}")
    print(f"Size: {len(output)} bytes; SHA-256: {hashlib.sha256(output).hexdigest()}")


if __name__ == "__main__":
    main()
