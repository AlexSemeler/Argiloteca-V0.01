"""Private OpenAlex PDF staging. Never creates or edits repository records."""
import fcntl
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from .knowledge import MAX_BYTES


class Staging:
    def __init__(self, library_root):
        self.root = Path(library_root) / 'openalex-staging'
        self.db = self.root / 'catalog.sqlite3'

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            yield connection
        finally:
            connection.close()

    def listing(self, page=1, q='', category=''):
        if not self.db.is_file():
            return [], 0
        with self.connect() as c:
            where = " WHERE (?='' OR search LIKE ?) AND (?='' OR category=?)"
            params = (q.lower(), '%' + q.lower().replace('%', '').replace('_', '') + '%', category, category)
            total = c.execute('SELECT count(*) FROM pdfs' + where, params).fetchone()[0]
            order = " ORDER BY CASE category WHEN 'candidate_open_license' THEN 0 WHEN 'conditional_license_review' THEN 1 ELSE 2 END,title,id"
            rows = c.execute('SELECT data FROM pdfs' + where + order + ' LIMIT 20 OFFSET ?', (*params, (page-1)*20)).fetchall()
        return [json.loads(r[0]) for r in rows], total

    def get(self, item_id):
        if not re.fullmatch(r'[a-f0-9]{64}', item_id) or not self.db.is_file():
            raise KeyError(item_id)
        with self.connect() as c:
            row = c.execute('SELECT data FROM pdfs WHERE id=?', (item_id,)).fetchone()
        if not row:
            raise KeyError(item_id)
        return json.loads(row[0])

    def verified_file(self, item):
        name = item['filename']
        if not re.fullmatch(r'doi_[a-f0-9]{64}\.pdf', name):
            raise ValueError('Invalid filename')
        folder = self.root / 'pdfs'
        path = folder / name
        if path.is_symlink() or path.resolve().parent != folder.resolve() or not path.is_file():
            raise ValueError('Missing or unsafe file')
        if path.stat().st_size != item['bytes']:
            raise ValueError('Changed size')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            if not stream.read(1024).lstrip().startswith(b'%PDF-'):
                raise ValueError('Not a PDF')
            stream.seek(0)
            for block in iter(lambda: stream.read(1024*1024), b''):
                digest.update(block)
        if digest.hexdigest() != item['sha256']:
            raise ValueError('Changed SHA256')
        return path


def live_matches(item):
    """Recheck all exact identities, including restricted matches, before linking."""
    from flask import current_app
    from invenio_db import db
    from invenio_rdm_records.records.models import RDMRecordMetadata
    from ..openalex.adapters import converter
    from ..openalex.service import tokens
    metadata, _, _ = converter(current_app.config['ARGILOTECA_OPENALEX_ROOT'])
    wanted = tokens({'metadata': {'identifiers': [
        {'identifier': item['doi']}, {'identifier': item['openalex_id']}]}}, metadata)
    matches = {}
    for (data,) in db.session.query(RDMRecordMetadata.json).filter(RDMRecordMetadata.deletion_status=='P').yield_per(100):
        if tokens(data, metadata) & wanted:
            rid = str(data.get('id', ''))
            if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', rid):
                matches[rid] = data
    return matches, metadata, wanted


def register(bp):
    # The existing blueprint supplies administrative authorization, CSRF, locale,
    # private/no-store responses and the normal approval/indexing workflow.
    from .admin import library, t, extract_document

    def load(item_id):
        lib = library()
        stage = Staging(lib.root)
        try:
            return lib, stage, stage.get(item_id)
        except KeyError:
            abort(404)

    @bp.get('/openalex-pdfs/')
    def openalex_pdfs():
        try:
            page = max(1, min(10000, int(request.args.get('page', 1))))
        except ValueError:
            abort(400)
        category = request.args.get('category', '')
        if category not in ('', 'candidate_open_license', 'conditional_license_review', 'license_not_confirmed'):
            abort(400)
        q = request.args.get('q', '')[:100]
        stage = Staging(library().root)
        rows, total = stage.listing(page, q, category)
        return render_template('semantic-ui/argiloteca/admin_openalex_pdfs.html', rows=rows, total=total, page=page,
                               pages=max(1, (total+19)//20), q=q, category=category, item=None)

    @bp.get('/openalex-pdfs/<item_id>')
    def openalex_pdf_detail(item_id):
        lib, stage, item = load(item_id)
        with lib.connect() as c:
            row = c.execute('SELECT doc,version FROM versions WHERE sha=?', (item['sha256'],)).fetchone()
        return render_template('semantic-ui/argiloteca/admin_openalex_pdfs.html', item=item, existing=dict(row) if row else None)

    @bp.get('/openalex-pdfs/<item_id>/pdf')
    def openalex_pdf_file(item_id):
        _, stage, item = load(item_id)
        try:
            path = stage.verified_file(item)
        except (ValueError, OSError):
            abort(409, description=t('Arquivo indisponível ou alterado. Confira a coleta original.', 'File unavailable or changed. Check the original collection.'))
        response = send_file(path, mimetype='application/pdf', as_attachment=False, download_name=item['filename'], conditional=True)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        return response

    @bp.post('/openalex-pdfs/<item_id>/prepare')
    def openalex_pdf_prepare(item_id):
        lib, stage, item = load(item_id)
        rights = request.form.get('rights', '').strip()[:3000]
        if request.form.get('confirm_identity') != 'yes' or request.form.get('confirm_rights') != 'yes' or not rights:
            abort(400, description=t('Confira a identidade do PDF e informe as condições de uso.', 'Check PDF identity and provide usage conditions.'))
        if item['bytes'] > MAX_BYTES:
            abort(400, description=t('O PDF excede 50 MiB. Prepare uma versão adequada para a biblioteca.', 'PDF exceeds 50 MiB. Prepare a suitable library version.'))
        try:
            path = stage.verified_file(item)
            matches, metadata, wanted = live_matches(item)
            if len(matches) > 1:
                abort(409, description=t('Mais de um registro corresponde aos identificadores. Revise os vínculos antes de continuar.', 'Multiple records match the identifiers. Review links before continuing.'))
            rid = next(iter(matches), '')
            if rid:
                from .service import public_record
                from ..openalex.service import tokens
                record = public_record(rid)
                if not record or not (tokens(record, metadata) & wanted):
                    abort(409, description=t('O vínculo mudou ou o registro não é público. Revise a correspondência.', 'The link changed or the record is not public. Review the match.'))
            meta = {'title': item['title'], 'doi': item['doi'], 'url': 'https://openalex.org/'+item['openalex_id'],
                    'record_id': rid, 'origin': 'OpenAlex '+item['openalex_id']+' · dois_20261017_134327_rywswrsg · '+item['filename'],
                    'rights': rights, 'access': request.form.get('access', 'restricted')}
            if rid:
                bibliography = record.get('metadata', {})
                meta['authors'] = '; '.join(str(c.get('person_or_org', {}).get('name', '')) for c in bibliography.get('creators', []))[:3000]
                meta['year'] = str(bibliography.get('publication_date', ''))[:4]
            with (lib.root/'openalex-prepare.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with path.open('rb') as stream:
                    result = lib.upload(stream, meta, current_user.get_id())
                with lib.connect() as c:
                    lib.audit(c, current_user.get_id(), 'openalex_pdf_review', result['doc'],
                              {'sha256': item['sha256'], 'doi': item['doi'], 'openalex_id': item['openalex_id'],
                               'record_id': rid, 'duplicate': result['duplicate'], 'rights': rights, 'identity_confirmed': True})
            if not result['duplicate']:
                extract_document.delay(result['doc'], result['version'], request.form.get('ocr')=='yes')
            flash(t('PDF já cadastrado; aberta a fonte existente, sem alterar seus vínculos.', 'PDF already registered; opened the existing source without changing its links.') if result['duplicate'] else
                  t('PDF enviado para extração. Confira e aprove as páginas; depois use “Indexar páginas aprovadas no ArgiloClay”.', 'PDF queued for extraction. Check and approve pages, then use “Index approved pages in ArgiloClay”.'), 'success')
            return redirect(url_for('.detail', doc=result['doc'], version=result['version'], _anchor='admin-feedback'))
        except (ValueError, OSError, sqlite3.IntegrityError):
            abort(409, description=t('Não foi possível preparar o PDF. Confira o arquivo, as condições de uso e tente novamente.', 'Could not prepare PDF. Check the file and usage conditions, then retry.'))
