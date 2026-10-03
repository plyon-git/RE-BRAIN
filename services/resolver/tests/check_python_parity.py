#!/usr/bin/env python3
"""Dependency-free Python identity contract and optional live Rust parity test."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _optional_string(record, field):
    value = record.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return value


def resolve_identity(record):
    county = record.get("county_fips")
    if not isinstance(county, str) or len(county) != 5 or not all("0" <= c <= "9" for c in county):
        raise ValueError("county_fips must be exactly five ASCII digits")
    parcel = _optional_string(record, "parcel_id")
    address = _optional_string(record, "address")
    state = _optional_string(record, "state")
    if len(parcel.encode("utf-8")) > 128 or len(address.encode("utf-8")) > 512 or len(state.encode("utf-8")) > 32:
        raise ValueError("identity field exceeds UTF-8 byte limit")
    state = state.strip().upper()
    if state and (len(state) != 2 or not all("A" <= c <= "Z" for c in state)):
        raise ValueError("state must be an ASCII two-letter abbreviation")
    normalized_parcel = "".join(c for c in parcel.upper() if c.isascii() and c.isalnum())
    normalized_address = " ".join("".join(c if c.isascii() and c.isalnum() else " " for c in address.upper()).split())
    address_key = normalized_address + ("|" + state if state else "")
    if normalized_parcel:
        property_id = county + "-" + normalized_parcel
    else:
        if not normalized_address or not state:
            raise ValueError("empty parcel requires address and state")
        property_id = county + "-ADDR-" + hashlib.sha256(address_key.encode("utf-8")).hexdigest()[:20]
    return {"property_id": property_id, "normalized_parcel_id": normalized_parcel, "address_key": address_key}


def request_json(url, payload=None):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("BRAIN_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["BRAIN_API_KEY"]
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers)
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="also verify a running Rust resolver")
    args = parser.parse_args()
    fixture = json.loads(Path(__file__).with_name("identity_golden.json").read_text())
    for case in fixture["valid"]:
        assert resolve_identity(case["record"]) == case["expected"], case["name"]
    for case in fixture["invalid"]:
        try:
            resolve_identity(case["record"])
        except ValueError:
            continue
        raise AssertionError("accepted invalid record: " + case["name"])
    if args.url:
        base = args.url.rstrip("/")
        assert request_json(base + "/health")["status"] == "ok"
        response = request_json(base + "/resolve", {"records": [c["record"] for c in fixture["valid"]]})
        assert response["results"] == [c["expected"] for c in fixture["valid"]]
        for records in [[], [fixture["invalid"][0]["record"]]]:
            try:
                request_json(base + "/resolve", {"records": records})
            except HTTPError as exc:
                assert exc.code == 400
                assert "error" in json.load(exc)
            else:
                raise AssertionError("invalid batch was accepted")
    print(f"Identity parity passed: {len(fixture['valid'])} valid and {len(fixture['invalid'])} invalid cases" + ("; live Rust HTTP verified" if args.url else "; offline fixtures verified"))


if __name__ == "__main__":
    main()
