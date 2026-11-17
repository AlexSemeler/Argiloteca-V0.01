"""Read-only historical library and append-only private trio storage."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from functools import lru_cache

CODE = re.compile(r'ARC-[A-F0-9]{16}')
FILE = re.compile(r'ARC-[A-F0-9]{16}_[NGCX](?:_D\d+)?\.(raw|ras|gsa)', re.I)
ITEM_ID = re.compile(r'[a-f0-9]{24}')


@lru_cache(maxsize=2)
def _index(path, mtime, size):
    data = json.loads(Path(path).read_text())
    if data['schema_version'] != 1:
        raise ValueError('Invalid historical index')
    return data


class AdminRawStore:
    def __init__(self, library, uploads):
        self.library, self.uploads = Path(library), Path(uploads)

    def historical(self):
        path = self.library / 'index.json'
        stat = path.stat()
        return _index(str(path), stat.st_mtime_ns, stat.st_size)

    def uploaded(self):
        if not self.uploads.exists():
            return []
        rows = []
        for directory in sorted(self.uploads.glob('ARC-*'), reverse=True):
            if CODE.fullmatch(directory.name) and directory.is_dir() and not directory.is_symlink():
                manifest = json.loads((directory / 'manifest.json').read_text())
                rows.extend(manifest['rows'])
        return sorted(rows, key=lambda r: r['classified_at'], reverse=True)

    def rows(self):
        from .raw_removal import retired
        removed=retired()
        return [r for r in self.uploaded()+self.historical()['rows'] if r['id'] not in removed and r['filename'] not in removed]

    def get(self, item_id):
        if not ITEM_ID.fullmatch(item_id):
            raise KeyError(item_id)
        row = next((r for r in self.rows() if r['id'] == item_id), None)
        if not row:
            raise KeyError(item_id)
        return row

    def content(self, row):
        from .raw_removal import retired
        if row['id'] in retired():raise FileNotFoundError('RAW retired')
        if not row['curve_available'] or not FILE.fullmatch(row['filename']):
            raise FileNotFoundError('Curve unavailable')
        folder = self.uploads / row['sample_code'] / 'files' if row['classification_kind'] == 'new_provisional' else self.library / 'files'
        path = folder / row['filename']
        if path.is_symlink() or path.resolve().parent != folder.resolve():
            raise ValueError('Invalid file location')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('Derivative integrity mismatch')
        return content

    def commit_trio(self, *, code, rows, originals, derivatives, provenance, analysis):
        if not CODE.fullmatch(code) or len(rows) != 3:
            raise ValueError('Invalid trio')
        self.uploads.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = self.uploads / ('.pending-' + secrets.token_hex(16))
        target = self.uploads / code
        staging.mkdir(mode=0o700)
        try:
            for name in ('originals', 'files'):
                (staging / name).mkdir(mode=0o700)
            for role, content in originals.items():
                path = staging / 'originals' / (role + '.raw')
                with path.open('wb') as stream:
                    stream.write(content); stream.flush(); os.fsync(stream.fileno())
                path.chmod(0o600)
            for filename, content in derivatives.items():
                if not FILE.fullmatch(filename):
                    raise ValueError('Invalid anonymous filename')
                path = staging / 'files' / filename
                with path.open('wb') as stream:
                    stream.write(content); stream.flush(); os.fsync(stream.fileno())
                path.chmod(0o600)
            for name, data in [('manifest.json', {'schema_version': 1, 'rows': rows}),
                               ('provenance.private.json', provenance), ('analysis.json', analysis)]:
                path = staging / name
                with path.open('w') as stream:
                    json.dump(data, stream, ensure_ascii=False, allow_nan=False)
                    stream.flush(); os.fsync(stream.fileno())
                path.chmod(0o600)
            # Serialize only the commit and deduplicate retries; historical data is immutable.
            lock_path = self.uploads / '.commit.lock'
            with lock_path.open('a') as lock:
                lock_path.chmod(0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)
                for prior in self.uploads.glob('ARC-*/provenance.private.json'):
                    saved = json.loads(prior.read_text())
                    from .raw_removal import retired
                    prior_rows=json.loads((prior.parent/'manifest.json').read_text())['rows']
                    if any(r['id'] in retired(fresh=True) for r in prior_rows):continue
                    if saved.get('submission_fingerprint') == provenance['submission_fingerprint']:
                        shutil.rmtree(staging)
                        return saved['sample_code']
                if target.exists():
                    raise ValueError('Submission already exists')
                os.rename(staging, target)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return code

    def analysis(self, code):
        if not CODE.fullmatch(code):
            raise KeyError(code)
        return json.loads((self.uploads / code / 'analysis.json').read_text())
