"""Small, bounded downloader for the public Hugging Face railway run dataset."""

from __future__ import annotations

import json
import re
import time
import concurrent.futures
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd


DATASET = "yadavsaurabh/indian-railways-runs"
BASE = "https://datasets-server.huggingface.co"
RAW = "https://huggingface.co/datasets/yadavsaurabh/indian-railways-runs/resolve/main"


def _get_json(url: str, timeout: int = 90) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "railway-minor-project/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _get_json_retry(url: str, timeout: int = 90, attempts: int = 4) -> dict:
    """Retry temporary Hugging Face throttling and gateway failures politely."""
    for attempt in range(attempts):
        try:
            return _get_json(url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = min(60, float(retry_after)) if retry_after and retry_after.isdigit() else min(30, 2 ** attempt * 3)
            print(f"Hugging Face returned HTTP {exc.code}; retrying in {delay:g}s.")
            time.sleep(delay)


def _sample_station_train_ids(station: str, sample_rows: int = 4_000) -> list[str]:
    """Fallback discovery by evenly sampling the viewer's ordinary rows API."""
    if sample_rows < 100:
        raise ValueError("Fallback sample must cover at least 100 rows.")
    params = urllib.parse.urlencode({"dataset": DATASET, "config": "default", "split": "train",
                                     "offset": 0, "length": 1})
    try:
        metadata = _get_json_retry(f"{BASE}/rows?{params}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Hugging Face row endpoint is unavailable: {exc}. Retry later or use --csv with a local export.") from exc
    total = int(metadata.get("num_rows_total", 0))
    if total < 1:
        raise RuntimeError("Hugging Face rows endpoint returned no rows to sample.")
    page_size = 100
    pages = max(1, min((sample_rows + page_size - 1) // page_size,
                       (total + page_size - 1) // page_size))
    offsets = sorted({min(total - page_size, int((i + .5) * total / pages)) for i in range(pages)})

    def read_page(offset: int) -> list[str]:
        query = urllib.parse.urlencode({"dataset": DATASET, "config": "default", "split": "train",
                                        "offset": offset, "length": page_size})
        page = _get_json_retry(f"{BASE}/rows?{query}")
        time.sleep(.25)
        return [str(item.get("row", {}).get("train_no")).zfill(5)
                for item in page.get("rows", [])
                if str(item.get("row", {}).get("station_code", "")).upper() == station]

    found: set[str] = set()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for train_ids in pool.map(read_page, offsets):
                found.update(train_ids)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Hugging Face row sampling failed: {exc}. Retry later or use --csv with a local export.") from exc
    if not found:
        raise RuntimeError(f"No {station} rows found in a {len(offsets) * page_size:,}-row sample of the indexed dataset.")
    print(f"Station filter is unavailable; sampled {len(offsets) * page_size:,} indexed rows and found {len(found)} {station} train IDs.")
    return sorted(found)


def station_train_ids(station: str, max_index_rows: int = 50_000,
                      fallback_sample_rows: int = 4_000) -> list[str]:
    """Ask the dataset viewer for matching station rows and return train IDs.

    The viewer filter avoids scanning/downloading the full 34.7 GB collection.
    `max_index_rows` caps API work and is configurable for stations with many
    historical observations. The viewer's parquet export may cover only a
    partial slice of the source, so the returned IDs are a bounded sample.
    """
    station = station.upper().strip()
    if not re.fullmatch(r"[A-Z0-9]{2,8}", station):
        raise ValueError(f"Invalid station code: {station!r}")
    where = f'"station_code"=\'{station}\''
    ids: set[str] = set()
    offset, page_size = 0, 100
    while offset < max_index_rows:
        params = urllib.parse.urlencode({"dataset": DATASET, "config": "default", "split": "train",
                                         "where": where, "offset": offset, "length": page_size})
        try:
            result = _get_json(f"{BASE}/filter?{params}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Hugging Face station filter failed ({exc}); switching to sampled row discovery.")
            return _sample_station_train_ids(station, fallback_sample_rows)
        rows = result.get("rows", [])
        for item in rows:
            train_no = item.get("row", {}).get("train_no")
            if train_no is not None:
                ids.add(str(train_no).zfill(5))
        if not rows:
            break
        offset += len(rows)
        if len(rows) < page_size:
            break
        time.sleep(.15)
    if not ids:
        raise RuntimeError(f"No train numbers returned for {station}. The viewer may be unavailable or the station absent from its indexed slice.")
    return sorted(ids)


def download_train(train_no: str, cache_dir: str | Path) -> Path:
    train_no = str(train_no).zfill(5)
    half = "trains" if train_no[0] in "01234" else "trains_1"
    target = Path(cache_dir) / half / f"{train_no}.csv"
    if target.exists() and target.stat().st_size:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RAW}/{half}/{train_no}.csv?download=true"
    request = urllib.request.Request(url, headers={"User-Agent": "railway-minor-project/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not download train file {train_no}: {exc}") from exc
    if not payload.lstrip(b"\xef\xbb\xbf").lower().startswith(b"date,"):
        raise RuntimeError(f"Unexpected response for train file {train_no}; check the repository path or license terms.")
    target.write_bytes(payload)
    return target


def _cached_train_ids_for_station(cache_dir: Path, station: str) -> list[str]:
    """Return cached run files that contain the requested station code."""
    found = []
    for path in cache_dir.glob("**/*.csv"):
        try:
            codes = pd.read_csv(path, usecols=["station_code"], dtype=str)["station_code"]
        except (ValueError, OSError, pd.errors.ParserError):
            continue
        if codes.str.upper().eq(station).any():
            found.append(path.stem.zfill(5))
    return sorted(set(found))


def fetch_station_corridor(stations: list[str], cache_dir: str | Path,
                           max_trains_per_station: int = 10,
                           max_index_rows: int = 50_000,
                           fallback_sample_rows: int = 4_000) -> pd.DataFrame:
    """Download complete run histories for trains serving one or more stations."""
    cache_dir = Path(cache_dir)
    ids: set[str] = set()
    for station in stations:
        station = station.upper().strip()
        cached = _cached_train_ids_for_station(cache_dir, station)
        if cached:
            found = cached
            print(f"{station}: reusing {len(found)} cached train histories.")
        else:
            try:
                found = station_train_ids(station, max_index_rows=max_index_rows,
                                          fallback_sample_rows=fallback_sample_rows)
            except (RuntimeError, urllib.error.URLError) as exc:
                if ids:
                    print(f"{station}: discovery failed ({exc}); continuing with the station corridor already cached or found.")
                    continue
                raise
        if len(found) > max_trains_per_station:
            # Spread the bounded sample across train numbers rather than always
            # selecting only the numerically lowest services.
            positions = [round(i * (len(found) - 1) / (max_trains_per_station - 1))
                         for i in range(max_trains_per_station)] if max_trains_per_station > 1 else [len(found) // 2]
            selected = [found[i] for i in positions]
        else:
            selected = found
        ids.update(selected)
        print(f"{station.upper()}: discovered {len(found)} train IDs; selected {min(len(found), max_trains_per_station)}")
    paths = []
    for index, train_no in enumerate(sorted(ids), start=1):
        paths.append(download_train(train_no, cache_dir))
        if index % 25 == 0 or index == len(ids):
            print(f"Downloaded/cached {index}/{len(ids)} train histories")
    pieces = [pd.read_csv(p, dtype={"train_no": str}, low_memory=False) for p in paths]
    if not pieces:
        raise RuntimeError("No train histories were downloaded.")
    return pd.concat(pieces, ignore_index=True)

