"""Manual, bounded Photon lookup. This module never writes scientific records."""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
import requests


class LookupError(Exception):
    def __init__(self, code, status=503):
        self.code, self.status = code, status
        super().__init__(code)


def candidates(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('features'), list):
        raise LookupError('unavailable')
    result = []
    for feature in payload['features'][:5]:
        if not isinstance(feature, dict): continue
        geometry = feature.get('geometry') or {}
        coords = geometry.get('coordinates') or []
        if geometry.get('type') != 'Point' or not isinstance(coords, list) or len(coords) < 2: continue
        lon, lat = coords[:2]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)): continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): continue
        props = feature.get('properties') or {}
        if not isinstance(props, dict): continue
        parts = list(dict.fromkeys(str(props[k])[:150] for k in ('name', 'street', 'city', 'state', 'country') if props.get(k)))
        result.append({'label': ', '.join(parts) or f'{lat}, {lon}', 'latitude': lat, 'longitude': lon})
    return result


def lookup(query, endpoint, folder, *, fetch=requests.get, now=time.time):
    query = ' '.join(query.split())
    if not 3 <= len(query) <= 180:
        raise LookupError('invalid_query', 422)
    url = urlsplit(endpoint)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise LookupError('unavailable')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    database = folder / 'places.sqlite3'
    # Shared by all UI workers; rate reservation is committed before networking.
    with closing(sqlite3.connect(database, timeout=2)) as connection, connection:
        os.chmod(database, 0o600)
        connection.execute('CREATE TABLE IF NOT EXISTS places (key TEXT PRIMARY KEY, body TEXT, created REAL)')
        connection.execute('CREATE TABLE IF NOT EXISTS throttle (id INTEGER PRIMARY KEY, next_at REAL)')
        stamp = now(); key = hashlib.sha256((endpoint + '\n' + query.casefold()).encode()).hexdigest()
        connection.execute('BEGIN IMMEDIATE')
        cached = connection.execute('SELECT body FROM places WHERE key=? AND created>?', (key, stamp-604800)).fetchone()
        if cached:
            connection.commit()
            return {'results': json.loads(cached[0]), 'cached': True, 'provider': 'Photon / OpenStreetMap'}
        next_at = connection.execute('SELECT next_at FROM throttle WHERE id=1').fetchone()
        if next_at and next_at[0] > stamp:
            raise LookupError('rate_limit', 429)
        connection.execute('INSERT OR REPLACE INTO throttle VALUES (1, ?)', (stamp+1.1,))
        connection.commit()
    try:
        with fetch(endpoint, params={'q': query, 'limit': 5}, headers={
            'User-Agent': 'Argiloteca-coordinate-curation/1.0 (manual place lookup)',
            'Accept': 'application/json'}, timeout=(4, 10), stream=True, allow_redirects=False) as response:
            if response.status_code == 429: raise LookupError('rate_limit', 429)
            if response.status_code != 200: raise LookupError('unavailable')
            body = bytearray()
            for chunk in response.iter_content(8192):
                body.extend(chunk)
                if len(body) > 1048576: raise LookupError('unavailable')
            result = candidates(json.loads(body))
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise LookupError('unavailable') from None
    with closing(sqlite3.connect(database, timeout=2)) as connection, connection:
        connection.execute('DELETE FROM places WHERE created < ?', (stamp-604800,))
        connection.execute('INSERT OR REPLACE INTO places VALUES (?, ?, ?)', (key, json.dumps(result), stamp))
        connection.execute('DELETE FROM places WHERE key NOT IN (SELECT key FROM places ORDER BY created DESC LIMIT 512)')
    return {'results': result, 'cached': False, 'provider': 'Photon / OpenStreetMap'}
