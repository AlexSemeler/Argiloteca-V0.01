"""Thin authenticated HTTP adapters for raw consultation and new trio submissions."""
from functools import wraps
import io
from pathlib import Path

from flask import abort, current_app, g, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from flask_wtf.csrf import generate_csrf
from flask_babel import get_locale

from .admin_raw_store import AdminRawStore
from .admin_raw_service import MAX_FILE_BYTES, preview, submit_trio
from .restricted_review import can_review
from .admin_raw_curation import CurationBlocked, CurationLinks, eligibility, linked_state, prepare_draft
from .admin_ngc_report import ReportUnavailable, build_report, family_view, final_archive, plotly_source, report_assets


class InvalidLibraryFilter(Exception):
    pass


def admin_only(function):
    @wraps(function)
    def call(*args, **kwargs):
        if not can_review():
            abort(403)
        return function(*args, **kwargs)
    return call


def store():
    return AdminRawStore(current_app.config.get('ARGILOTECA_ADMIN_RAW_LIBRARY',
        str(Path(current_app.instance_path) / 'app_data/drx-library')),
        current_app.config.get('ARGILOTECA_ADMIN_RAW_UPLOADS',
        str(Path(current_app.instance_path) / 'data/drx-admin-trios')))


def curation_links():
    return CurationLinks(current_app.config.get('ARGILOTECA_ADMIN_RAW_CURATION',
        str(Path(current_app.instance_path) / 'data/drx-admin-curation')))


def joint_report(repository, row, *, include_curves=False):
    report = build_report(repository, row, include_curves=include_curves)
    report['families'] = [family_view(f) for f in report['families']]
    return report


def listing(rows, args):
    q = str(args.get('q', '')).strip()[:100]
    prep, access, status = (args.get(k, '') for k in ('prep', 'access', 'status'))
    if prep not in {'', 'N', 'G', 'C', 'X'} or access not in {'', 'restricted', 'public_snapshot'} or status not in {'', 'classified', 'recovered_review', 'unreadable', 'new_provisional'}:
        raise InvalidLibraryFilter()
    try:
        page = max(1, int(args.get('page', '1')))
    except (TypeError, ValueError):
        raise InvalidLibraryFilter()
    selected = [r for r in rows if (not prep or prep == r['preparation'])
        and (not access or access == r['access']) and (not status or status == r['status'])
        and (not q or q.casefold() in (r['filename'] + ' ' + str([c.get('mineral') for c in r['candidates']])).casefold())]
    pages = max(1, (len(selected)+19)//20); page = min(page, pages)
    return dict(rows=selected[(page-1)*20:page*20], total=len(selected), page=page, pages=pages,
                q=q, prep=prep, access=access, status=status)


def register_library(bp):
    @bp.after_request
    def private_library(response):
        if request.endpoint and request.endpoint.startswith('argiloteca_scientific.admin_raw_'):
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @bp.route('/administration/raw-library/', endpoint='admin_raw_library')
    @admin_only
    def library():
        repository = store()
        try:
            all_rows = repository.rows()
            context = listing(all_rows, request.args)
        except InvalidLibraryFilter:
            abort(400)
        except (OSError, ValueError, KeyError, TypeError):
            current_app.logger.warning('Administrative RAW library unavailable')
            return render_template('semantic-ui/argiloteca/admin_raw_library.html', unavailable=True), 503
        context.update(summary={'files': len(all_rows), 'curves': sum(r['curve_available'] for r in all_rows),
            'new_files': sum(r['classification_kind'] == 'new_provisional' for r in all_rows)},
            csrf_token=generate_csrf(), upload_limit_mb=MAX_FILE_BYTES//1024//1024)
        context['page_url'] = lambda page: url_for('.admin_raw_library', page=page,
            **{k:context[k] for k in ('q','prep','access','status')})
        return render_template('semantic-ui/argiloteca/admin_raw_library.html', **context)

    @bp.route('/administration/raw-library/<item_id>', endpoint='admin_raw_detail')
    @admin_only
    def detail(item_id):
        repository = store()
        try:
            row = repository.get(item_id)
            companions = [r for r in repository.rows() if r['sample_code'] == row['sample_code']]
            analysis = repository.analysis(row['sample_code']) if row['classification_kind'] == 'new_provisional' else None
        except (KeyError, FileNotFoundError):
            abort(404)
        link = curation_links().read(row['sample_code'])
        try:
            report = joint_report(repository, row)
        except (ReportUnavailable, OSError, ValueError, KeyError):
            report = None
        from .drx_links import analysis_for
        return render_template('semantic-ui/argiloteca/admin_raw_detail.html', row=row, companions=companions,
            analysis=analysis, report=report, curation=eligibility(repository, row),
            reprocessed=analysis_for(row),
            draft_link=link, linked_state=linked_state(link, g.identity), csrf_token=generate_csrf(), curation_error=None)

    @bp.route('/administration/raw-library/<item_id>/prepare-draft', methods=['POST'], endpoint='admin_raw_prepare_draft')
    @admin_only
    def curated_draft(item_id):
        repository = store()
        try:
            row = repository.get(item_id)
        except (KeyError, FileNotFoundError):
            abort(404)
        try:
            result = prepare_draft(repository, row, curation_links(), request.form, g.identity)
        except Exception as error:
            reason = str(error) if isinstance(error, CurationBlocked) else 'native_draft_requires_review'
            current_app.logger.warning('Administrative trio draft preparation refused: %s', reason)
            companions = [r for r in repository.rows() if r['sample_code'] == row['sample_code']]
            link = curation_links().read(row['sample_code'])
            return render_template('semantic-ui/argiloteca/admin_raw_detail.html', row=row, companions=companions,
                analysis=repository.analysis(row['sample_code']) if row['classification_kind'] == 'new_provisional' else None,
                report=None,
                curation=eligibility(repository, row), draft_link=link, linked_state=linked_state(link, g.identity),
                csrf_token=generate_csrf(), curation_error=reason), 422
        return redirect('/uploads/' + result['draft_id'], code=303)

    @bp.route('/administration/raw-library/<item_id>/ngc', endpoint='admin_raw_ngc')
    @admin_only
    def ngc_evidence(item_id):
        repository = store()
        try:
            return jsonify(joint_report(repository, repository.get(item_id), include_curves=True))
        except (KeyError, FileNotFoundError):
            abort(404)
        except (ReportUnavailable, OSError, ValueError):
            return jsonify({'error':'saved_joint_analysis_unavailable'}), 422

    @bp.route('/administration/raw-library/<item_id>/ngc/report', endpoint='admin_raw_ngc_report')
    @admin_only
    def ngc_report(item_id):
        format_ = request.args.get('format','zip')
        if format_ not in {'zip','html','json'}:
            abort(400)
        repository = store()
        try:
            row = repository.get(item_id)
            report = joint_report(repository, row, include_curves=format_!='json')
        except (KeyError, FileNotFoundError):
            abort(404)
        except (ReportUnavailable, OSError, ValueError):
            return jsonify({'error':'saved_joint_analysis_unavailable'}), 422
        if format_ == 'json':
            response = jsonify(report)
            response.headers['Content-Disposition'] = 'attachment; filename="'+row['sample_code']+'-NGC.json"'
            return response
        pt = get_locale().language == 'pt'
        html = render_template('semantic-ui/argiloteca/admin_ngc_report.html', report=report,
            report_lang='pt-BR' if pt else 'en', review_text=lambda a,b:a if pt else b,
            t=lambda a,b:a if pt else b, plotly_js=plotly_source(), licenses=report_assets()['licenses'],
            report_brand_header=report_assets()['brand_header'], report_style=report_assets()['print_css'],
            report_font=report_assets()['font_data'] if format_=='zip' else url_for('argiloteca.static',filename='fonts/catamaran/catamaran-latin.woff2'))
        if format_ == 'html':
            return html
        return send_file(io.BytesIO(final_archive(repository,row,report,html)),
            mimetype='application/zip',as_attachment=True,download_name=row['sample_code']+'-NGC.zip')

    @bp.route('/administration/raw-library/<item_id>/curve', endpoint='admin_raw_curve')
    @admin_only
    def curve(item_id):
        try:
            return jsonify(preview(store(), item_id))
        except (KeyError, FileNotFoundError):
            abort(404)
        except Exception:
            current_app.logger.warning('Administrative RAW curve could not be read')
            return jsonify({'error': 'curve_unavailable_requires_review'}), 422

    @bp.route('/administration/raw-library/trios', methods=['POST'], endpoint='admin_raw_submit')
    @admin_only
    def submit():
        if request.content_length and request.content_length > 3*MAX_FILE_BYTES + 1024*1024:
            abort(413)
        if set(request.files) != {'N','G','C'} or any(len(request.files.getlist(p)) != 1 for p in 'NGC'):
            return jsonify({'error': 'complete_confirmed_trio_required'}), 422
        files = {role: (request.files[role].filename or '', request.files[role].read(MAX_FILE_BYTES+1)) for role in 'NGC'}
        try:
            code = submit_trio(store(), files, preparation_confirmed=request.form.get('confirm_preparations') == 'yes', actor=current_user.get_id(), test_only=request.form.get('test_only') == 'yes')
        except ValueError as error:
            known = {'complete_confirmed_trio_required','invalid_raw_or_size','raw_two_theta_required',
                     'curve_range_requires_review','declared_wavelength_required','duplicate_profiles'}
            reason = str(error) if str(error) in known else 'unsupported_or_invalid_raw'
            return jsonify({'error': reason}), 422
        except Exception:
            current_app.logger.exception('New restricted trio submission failed')
            return jsonify({'error': 'submission_failed_no_publication'}), 503
        repository = store()
        first = next(r for r in repository.uploaded() if r['sample_code']==code and r['preparation']=='N')
        location = url_for('.admin_raw_detail', item_id=first['id'])+'#ngc-analysis'
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'sample_code': code, 'location': location, 'access': 'restricted', 'published': False}), 201
        return redirect(location, code=303)
