"""Offline, explicit RAW reclassification with restricted provenance and originals.

Never publishes records. The existing matcher remains primary; V2 and N/G/C
remain separate auxiliary evidence. Only proven layouts produce derivatives.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil

from argiloteca_drx_core.raw_lifecycle import (
    RULE, parse_lifecycle_raw, anonymize_raw101, preparation_from_name, validate_public_raw_files,
)
from .mineral_matcher import extract_peaks, match_reference, normalize_reference_payload, SOURCE_SHA256
from .reference_pilot_v2_service import evaluate_reference_pilot_v2
from .reference_pilot_ngc_shadow_service import evaluate_reference_pilot_ngc_shadow

TREATMENTS = {'N':'natural','G':'glicolado','C':'calcinado','X':'indeterminado'}

def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
    path.chmod(0o600)

def run(source, destination, restricted, reference, runtime_root):
    source, destination, restricted = map(lambda p: Path(p).resolve(), (source,destination,restricted))
    if destination.exists(): raise ValueError('Output exists; use a fresh version directory.')
    destination.mkdir(parents=True, mode=0o700)
    restricted.mkdir(parents=True, mode=0o700, exist_ok=True)
    original_backup = restricted / 'original-raw'
    if original_backup.exists(): raise ValueError('Original backup already exists; refusing overwrite.')
    original_backup.mkdir(mode=0o700)
    derivative_dir = destination/'raw'; derivative_dir.mkdir()
    paths = sorted(p for p in source.rglob('*') if p.is_file() and p.suffix.lower()=='.raw')
    refs = normalize_reference_payload(json.loads(Path(reference).read_text()), 'versioned_local_cache')['records']
    now = datetime.now(timezone.utc).isoformat()
    groups, mapping, codes = defaultdict(list), [], {}
    rows, treatments, counts = [], [], Counter()
    with (restricted/'auxiliary-v2.jsonl').open('w') as auxiliary:
        for i, path in enumerate(paths):
            relative = path.relative_to(source)
            base, treatment = preparation_from_name(path.name)
            # Same spelling in two folders is not evidence of the same sample.
            group_key = (str(relative.parent), base.casefold())
            code = codes.setdefault(group_key, 'ARC-'+secrets.token_hex(8).upper())
            treatment = treatment or 'X'
            name = f'{code}_{treatment}.raw'
            # Duplicate preparations retain unique aliases and are held for review.
            sequence = sum(1 for entry in groups[code] if entry['treatment']==treatment)
            if sequence: name = f'{code}_{treatment}_D{sequence+1}.raw'
            data = path.read_bytes(); digest = hashlib.sha256(data).hexdigest()
            backup = original_backup/relative;backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            shutil.copyfile(path,backup);backup.chmod(0o600)
            if hashlib.sha256(backup.read_bytes()).hexdigest()!=digest: raise ValueError('Backup integrity failed.')
            item = {'filename':name,'sample_code':code,'path':str(Path(runtime_root)/'raw'/name),
                    'classified_at':now,'status':'error','error_message':None,'metadata':{},'peaks':[],
                    'candidates':[],'publication_eligible':False,'lifecycle_rule':RULE}
            entry = {'source_path':str(path),'relative_path':str(relative),'source_sha256':digest,
                     'public_code':code,'public_filename':name,'treatment':treatment,
                     'backup_path':str(backup),'derivative_sha256':None}
            try:
                curve = parse_lifecycle_raw(data)
                metadata = dict(curve.metadata)
                # Do not expose original hashes or free-form legacy metadata.
                item['metadata'] = {k:v for k,v in metadata.items() if k in {
                    'parser_version','lifecycle_rule','detected_format','axis_provenance','two_theta_start',
                    'two_theta_end','step','points','data_offset','measurement_complete','measurement_status',
                    'binary_anonymization_supported','wavelength_angstrom','warnings'}}
                item['peaks'] = extract_peaks(curve.two_theta,curve.intensity,max_peaks=14)
                item['candidates'] = match_reference(item['peaks'], refs)
                item['status']='ok';counts['analyzed']+=1
                if metadata.get('binary_anonymization_supported'):
                    anonymous = anonymize_raw101(data,code,treatment)
                    (derivative_dir/name).write_bytes(anonymous)
                    entry['derivative_sha256']=hashlib.sha256(anonymous).hexdigest()
                    item['metadata']['source_sha256']=entry['derivative_sha256']
                else: counts['unproven_binary_layout']+=1
                if metadata.get('measurement_status')=='aborted':counts['aborted']+=1
                if metadata.get('wavelength_angstrom') and metadata.get('binary_anonymization_supported'):
                    xy=[(x,y) for x,y in zip(curve.two_theta,curve.intensity) if x>0]
                    pilot=evaluate_reference_pilot_v2([r[0] for r in xy],[r[1] for r in xy],
                        wavelength_angstrom=metadata['wavelength_angstrom'],enabled=True,
                        preparation=treatment,source_sha256=entry['derivative_sha256'],
                        corrections={'axis_rule':RULE,'zero_angle_points_excluded':len(curve.two_theta)-len(xy),
                                     'automatic_axis_offset':False})
                    auxiliary.write(json.dumps({'public_code':code,'filename':name,'result':pilot})+'\n')
                    item['reference_pilot_auxiliary']={k:pilot[k] for k in ['rule_id','status','analysis_fingerprint']}
                    item['reference_pilot_auxiliary']['candidates']=[{k:c.get(k) for k in
                        ['mineral_id','mineral_name','source','source_id','source_url','score','score_kind','matched_peak_count']}
                        for c in pilot['candidates']]
                    counts['v2_auxiliary_evaluated']+=1
            except Exception as exc:
                # Never embed an exception with a source path/name in a public row.
                item['error_message']='RAW requires review: '+type(exc).__name__
                counts['errors']+=1
                entry['review_error']=type(exc).__name__
            entry['row']=item
            groups[code].append(entry);mapping.append(entry);rows.append(item)
            treatments.append({'filename':name,'path':item['path'],'sample_code':code,'sample_base':code,
                               'treatment':TREATMENTS[treatment],'confidence':'explicit_label' if treatment!='X' else 'review',
                               'name_evidence':[],'status':item['status'],'metadata':item['metadata']})
            if (i+1)%500==0: print(json.dumps({'processed':i+1,'total':len(paths)}),flush=True)
    ngc=[]
    for code, entries in groups.items():
        try:
            if len(entries)!=3 or {e['treatment'] for e in entries}!={'N','G','C'}:
                raise ValueError('missing_or_duplicate_preparation')
            files=[(e['public_filename'],(derivative_dir/e['public_filename']).read_bytes()) for e in entries]
            validate_public_raw_files(files)
            for entry in entries:entry['row']['publication_eligible']=True
            counts['eligible_trios']+=1
            try:
                context=evaluate_reference_pilot_ngc_shadow([
                    {'treatment':e['treatment'],'content':(derivative_dir/e['public_filename']).read_bytes()}
                    for e in entries],enabled=True)
                ngc.append({'sample_id':code,'result':context})
                counts['ngc_context_evaluated']+=1
            except ValueError as exc:
                counts['ngc_context_requires_review']+=1
                ngc.append({'sample_id':code,'status':'requires_review','reason':str(exc)})
        except (ValueError,FileNotFoundError):counts['held_groups']+=1
    public_rows=[r for r in rows if r['publication_eligible']]
    eligible_names={r['filename'] for r in public_rows}
    held_dir=restricted/'anonymized-held';held_dir.mkdir(mode=0o700)
    for path in derivative_dir.iterdir():
        if path.name not in eligible_names:
            shutil.move(str(path),held_dir/path.name)
        else:path.chmod(0o644)
    summary={'rule_id':RULE,'generated_at':now,'total_raw':len(paths),'total_groups':len(groups),
             **dict(counts),'eligible_raw':len(public_rows),'held_raw':len(rows)-len(public_rows),
             'reference_entries':len(refs),'references_with_lines':sum(bool(r.get('lines')) for r in refs),
             'primary_matcher_source_sha256':SOURCE_SHA256,'automatic_record_publications':0,
             'interpretation_policy':'auxiliary_candidates_not_curatorial_confirmation'}
    # Public snapshots contain only sanitized complete groups. The all-file audit is restricted.
    save(destination/'classificacao_mineralogica_raw.json',{'summary':summary,'results':public_rows})
    save(destination/'classificacao_tratamento_raw.json',{'summary':summary,'results':[r for r in treatments if r['filename'] in eligible_names]})
    save(destination/'ngc_auxiliary.json',{'summary':summary,'groups':ngc})
    save(restricted/'all-classifications.json',{'summary':summary,'results':rows})
    save(restricted/'identity-map.json',{'rule_id':RULE,'entries':[{k:v for k,v in e.items() if k!='row'} for e in mapping]})
    # Re-read every original: verify this run never mutated source bytes.
    assert all(hashlib.sha256(Path(e['source_path']).read_bytes()).hexdigest()==e['source_sha256'] for e in mapping)
    summary['originals_verified_unchanged']=len(mapping)
    save(destination/'summary.json',summary)
    for path in destination.iterdir():path.chmod(0o755 if path.is_dir() else 0o644)
    destination.chmod(0o755)
    print(json.dumps(summary),flush=True)
    return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ['source','destination','restricted','reference','runtime-root']:parser.add_argument('--'+flag,required=True)
    args=parser.parse_args()
    os.umask(0o077)
    run(args.source,args.destination,args.restricted,args.reference,args.runtime_root)

if __name__=='__main__':main()
