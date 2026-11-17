"""Read-only reports from saved administrative N/G/C evidence; no scientific rerun."""
import csv
import base64
import hashlib
import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path

from argiloteca_drx_core.raw_recovery import read_recoverable_pattern
from ..services.report_branding import report_brand_header, report_styles
from .admin_raw_service import preview
from ..drx.services.reference_pilot_ngc_shadow_service import SOURCES

SCHEMA = 'argiloteca.admin.ngc-report.v1'
FAMILIES = {'chlorite_group', 'smectite_group'}


class ReportUnavailable(ValueError):
    pass


def _projection(value, fields):
    return {key: value.get(key) for key in fields if key in value}


def build_report(repository, row, *, include_curves=False):
    """Expose only anonymous files and the evidence already saved for this submission."""
    if row['classification_kind'] != 'new_provisional':
        raise ReportUnavailable('saved_joint_analysis_required')
    rows = [r for r in repository.rows() if r['sample_code'] == row['sample_code']]
    if len(rows) != 3 or {r['preparation'] for r in rows} != set('NGC'):
        raise ReportUnavailable('complete_trio_required')
    by_role = {r['preparation']: r for r in rows}
    analysis = repository.analysis(row['sample_code'])
    ngc = analysis.get('ngc', {})
    for role in 'NGC':
        repository.content(by_role[role])  # Refuse a report for changed derivative bytes.
        origin = ngc.get('provenance', {}).get(role, {})
        if origin and origin.get('source_sha256') != by_role[role]['sha256']:
            raise ReportUnavailable('saved_analysis_source_mismatch')
    families = [_projection(f, ('family','status','rule_id','source','observations','missing_evidence','interpretation'))
                for f in ngc.get('family_context', []) if f.get('family') in FAMILIES]
    # Sources are the frozen engine's known literature links, never arbitrary saved URLs.
    for family in families:
        family['source'] = SOURCES['chlorite' if family['family']=='chlorite_group' else 'smectite']
    per_preparation = {}
    minerals = {}
    for role in 'NGC':
        saved = analysis.get('by_preparation', {}).get(role, {})
        primary, pilot = saved.get('primary', {}), saved.get('pilot', {})
        candidates = [_projection(c, ('mineral','score','matched_lines','reference_lines')) for c in primary.get('candidates', [])]
        for candidate in candidates:
            name = candidate.get('mineral')
            if name:
                minerals.setdefault(name, {'mineral':name,'by_preparation':{}})['by_preparation'][role] = candidate.get('score')
        per_preparation[role] = {
            'primary': {'status':primary.get('status','unavailable'), 'rule_sha256':primary.get('rule_sha256'), 'candidates':candidates},
            'structural_pilot': {'status':pilot.get('status','unavailable'), 'rule_id':pilot.get('rule_id'),
                'analysis_fingerprint':pilot.get('analysis_fingerprint'),
                'candidates':[_projection(c, ('mineral_name','score','source','source_id')) for c in pilot.get('candidates', [])]},
        }
    report = {'schema_version':SCHEMA, 'sample_code':row['sample_code'], 'access':'restricted',
        'test_only':any(r.get('test_only') for r in rows), 'analysis_at':row['classified_at'],
        'mode':analysis.get('mode','shadow'), 'ngc_status':ngc.get('status','unavailable'),
        'rule_id':ngc.get('rule_id'), 'analysis_fingerprint':ngc.get('analysis_fingerprint'),
        'parameters':ngc.get('parameters', {}),
        'source_analysis_sha256':hashlib.sha256(json.dumps(analysis,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
        'files':[_projection(by_role[role], ('filename','preparation','sha256','points','wavelength_angstrom','format')) for role in 'NGC'],
        'families':families, 'candidate_matrix':sorted(minerals.values(),key=lambda r:r['mineral'].casefold()),
        'by_preparation':per_preparation,
        'warnings':list(dict.fromkeys(ngc.get('warnings', []) + [
            'saved_shadow_evidence_no_reclassification','not_species_confirmation','not_probability_or_mass_fraction',
            'only_chlorite_and_smectite_family_rules_implemented','inconclusive_is_not_absence',
            'temperature_and_preparation_protocol_not_verified','experimental_thresholds_not_accuracy_validated'])),
        'existing_classifications_modified':False, 'record_publication_performed_by_report':False,
    }
    if include_curves:
        report['curves'] = [dict(preview(repository,by_role[role]['id']), preparation=role) for role in 'NGC']
    return report


def family_view(family):
    observations = family.get('observations', {})
    if family['family'] == 'chlorite_group':
        basal = observations.get('basal_by_treatment', {})
        evidence = [{'kind':'basal_14', 'values':{p:basal.get(p) for p in 'NGC'}}]
        companions = observations.get('companions_ng', {})
        for index, label in enumerate(('companion_7','companion_3_5')):
            evidence.append({'kind':label,'values':{p:(companions.get(p) or [None,None])[index]
                if len(companions.get(p) or [])>index else None for p in 'NG'}})
    else:
        evidence = [{'kind':'expansion_collapse', 'values':{p:observations.get(p) for p in 'NGC'}},
                    {'kind':'g_second_order', 'values':{'G':observations.get('G_second_order')}}]
    return {**family,'evidence':evidence}


@lru_cache(maxsize=1)
def plotly_source():
    path = Path(__file__).resolve().parents[1] / 'static/vendor/plotly-2.35.2/plotly.min.js'
    return path.read_text().replace('</script', '<\\/script')


@lru_cache(maxsize=1)
def report_assets():
    root = Path(__file__).resolve().parents[1] / 'static'
    font = root / 'fonts/catamaran/catamaran-latin.woff2'
    licenses = {'Catamaran':(font.parent/'OFL.txt').read_text(),
                'Plotly':(root/'vendor/plotly-2.35.2/LICENSE').read_text()}
    return {'font_data':'data:font/woff2;base64,'+base64.b64encode(font.read_bytes()).decode(), 'licenses':licenses, 'brand_header':report_brand_header(), 'print_css':report_styles()}


def curve_csv(repository, row):
    rows = {r['preparation']:r for r in repository.rows() if r['sample_code']==row['sample_code']}
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['sample_code','preparation','two_theta_degrees','intensity'])
    for role in 'NGC':
        curve = read_recoverable_pattern(repository.content(rows[role]))
        for x,y in zip(curve.x,curve.intensity):
            writer.writerow([row['sample_code'],role,x,y])
    return output.getvalue().encode('utf-8')


def final_archive(repository, row, report, html):
    """Portable, anonymous snapshot; no originals or hidden identity correspondence."""
    output = io.BytesIO()
    data = {k:v for k,v in report.items() if k!='curves'}
    json_data = json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode('utf-8')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('relatorio-ngc.html',html.encode('utf-8'))
        archive.writestr('resultados-ngc.json',json_data)
        archive.writestr('curvas-ngc.csv',curve_csv(repository,row))
        archive.writestr('LEIA-ME.txt',
            'Argiloteca - CPAA — N/G/C\n'
            'Abra relatorio-ngc.html no navegador; o grafico Plotly funciona sem internet. '
            'Use Imprimir para salvar em PDF.\n'
            'Open relatorio-ngc.html in a browser; the Plotly chart works offline. '
            'Use Print to save a PDF.\n'
            'Resultados exploratorios em modo sombra; nao sao laudo nem quantificacao de fases. '
            'Exploratory shadow-mode evidence, not a mineralogical certificate or phase quantification.\n'
            'O CSV preserva todos os pontos e intensidades dos derivados anonimos; '
            'a visualizacao usa envoltoria minima/maxima e normalizacao por curva.\n'
            'The CSV preserves all anonymous derivative points and intensities; '
            'the plot uses a min/max envelope and per-curve normalization.\n')
        archive.writestr('LICENCAS.txt', '\n\n'.join(name+'\n'+text for name,text in report_assets()['licenses'].items()))
        archive.writestr('SHA256SUMS.txt',hashlib.sha256(json_data).hexdigest()+'  resultados-ngc.json\n'
            +'\n'.join(f["sha256"]+'  '+f['filename']+' (source derivative, not bundled)' for f in report['files'])+'\n')
    return output.getvalue()
