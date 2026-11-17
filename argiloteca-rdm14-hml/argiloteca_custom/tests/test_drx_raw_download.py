"""Original-byte downloads by registry ID; no arbitrary path access."""

import pytest
from flask_babel import Babel

import argiloteca.views as views
from argiloteca.services import drx


@pytest.fixture
def raw_source(tmp_path, monkeypatch):
    root = tmp_path / 'raw'; root.mkdir()
    raw = root / 'Amostra á 01.RAW'; raw.write_bytes(b'RAW1.01\x00original\xff\x00')
    row = {'path': str(raw), 'filename': raw.name}
    identifier = drx._snapshot_id_for_path(str(raw))
    monkeypatch.setattr(drx, '_iter_raw_snapshot_rows', lambda: [row])
    monkeypatch.setattr(drx, 'SUPPORTED_LOCAL_IMPORT_ROOTS', (root,))
    return root, raw, row, identifier


def test_resolver_preserves_original_file_and_unicode_name(raw_source):
    _, raw, _, identifier = raw_source
    assert drx.resolve_snapshot_raw_download(identifier) == (raw.resolve(), raw.name)


def test_resolver_rejects_unknown_ids_paths_and_missing_files(raw_source):
    _, raw, _, identifier = raw_source
    for value in ['missing', str(raw), 'snapshot:../../secret', 'snapshot:'+'0'*20]:
        assert drx.resolve_snapshot_raw_download(value) is None
    raw.unlink()
    assert drx.resolve_snapshot_raw_download(identifier) is None


def test_resolver_rejects_outside_files_symlink_escape_and_non_raw(raw_source, tmp_path):
    root, raw, row, _ = raw_source
    outside = tmp_path / 'secret.raw'; outside.write_bytes(b'private')
    for source in [outside, root / 'escape.raw', root / 'notes.txt']:
        if source.name == 'escape.raw': source.symlink_to(outside)
        if source.suffix == '.txt': source.write_text('not RAW')
        row['path'] = str(source); row['filename'] = source.name
        assert drx.resolve_snapshot_raw_download(drx._snapshot_id_for_path(str(source))) is None


def test_download_aliases_attachment_range_and_missing_file(raw_source):
    from flask import Flask
    instance = Flask(__name__); Babel(instance)
    instance.register_blueprint(views.create_blueprint(instance))
    _, raw, _, identifier = raw_source
    for prefix in ['/api/argiloteca', '/argiloteca']:
        url = f'{prefix}/drx/raw-snapshot/{identifier}/download'
        response = instance.test_client().get(url)
        assert response.status_code == 200
        assert response.data == raw.read_bytes()
        assert response.mimetype == 'application/octet-stream'
        assert response.headers['Content-Disposition'].startswith('attachment;')
        assert 'filename*=UTF-8' in response.headers['Content-Disposition']
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        partial = instance.test_client().get(url, headers={'Range': 'bytes=0-3'})
        assert partial.status_code == 206 and partial.data == raw.read_bytes()[:4]
        missing = instance.test_client().get(f'{prefix}/drx/raw-snapshot/missing/download')
        assert missing.status_code == 404 and missing.json['success'] is False
        assert str(raw.parent) not in missing.get_data(as_text=True)
