"""Explicit restricted recovery; never publishes or reclassifies records.

Consumes a restricted audit manifest with source/backup hashes. Produces native
anonymous files and typed numerical sidecars for curator review only.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from argiloteca_drx_core.raw_recovery import RULE,anonymize_recoverable,read_recoverable_pattern
from argiloteca_drx_core.parser_errors import CurveParseError

def _hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def _save(path,payload):
    path.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False))
    path.chmod(0o600)

def run(manifest,destination,restricted):
    entries=json.loads(Path(manifest).read_text())
    destination=Path(destination).resolve();restricted=Path(restricted).resolve()
    if destination.exists():raise ValueError('Use a new recovery version; previous derivatives are immutable.')
    restricted.mkdir(parents=True,mode=0o700,exist_ok=True)
    # Verify all original/backup pairs before producing anything.
    for entry in entries:
        if _hash(Path(entry['source_path']))!=entry['source_sha256']:raise ValueError('Original hash changed; stop recovery.')
        if _hash(Path(entry['backup_path']))!=entry['source_sha256']:raise ValueError('Restricted backup integrity failed.')
    destination.mkdir(parents=True,mode=0o700)
    files=destination/'files';curves=destination/'curves'
    files.mkdir(mode=0o700);curves.mkdir(mode=0o700)
    counts=Counter();rows=[];ledger=[]
    for entry in entries:
        source=Path(entry['source_path']);data=source.read_bytes()
        identity={k:entry[k] for k in ['source_path','source_sha256','backup_path','public_code','public_filename']}
        try:
            content,extension,original=anonymize_recoverable(data,entry['public_code'],entry['treatment'])
            name=Path(entry['public_filename']).with_suffix(extension).name
            target=files/name
            if target.exists():raise ValueError('Duplicate derivative alias; refusing overwrite.')
            target.write_bytes(content);target.chmod(0o600)
            check=read_recoverable_pattern(target.read_bytes())
            assert (original.x,original.intensity,original.uncertainty,original.auxiliary)==(check.x,check.intensity,check.uncertainty,check.auxiliary)
            assert anonymize_recoverable(content,entry['public_code'],entry['treatment'])[0]==content
            digest=hashlib.sha256(content).hexdigest()
            # No original identity/hash or arbitrary header text in sidecars.
            metadata={k:v for k,v in check.metadata.items() if k not in {'body_lines','header_values','source_sha256'}}
            metadata.update(source_sha256=digest,sample_code=entry['public_code'],filename=name,
                            stored_in_record=False,requires_curatorial_release=True)
            _save(curves/(name+'.json'),{'schema_version':'argiloteca.drx.recovery.v1','metadata':metadata,
                'x':check.x,'intensity':check.intensity,'uncertainty':check.uncertainty,'auxiliary':check.auxiliary})
            row={'filename':name,'sample_code':entry['public_code'],'format':metadata['detected_format'],
                 'points':len(check.x),'axis_kind':metadata['axis_kind'],'wavelength_angstrom':metadata['wavelength_angstrom'],
                 'sha256':digest,'status':'recovered_requires_curatorial_review','publication_eligible':False}
            counts[metadata['detected_format']]+=1
            identity.update(derivative_path=str(target),derivative_sha256=digest,
                            original_metadata_repairs={k:original.metadata[k] for k in ['record_count_repaired','final_record_padding_completed'] if k in original.metadata})
        except CurveParseError as exc:
            row={'filename':entry['public_filename'],'sample_code':entry['public_code'],'status':'unrecoverable',
                 'reason':type(exc).__name__,'size_bytes':len(data),'publication_eligible':False}
            identity.update(reason=type(exc).__name__,message=str(exc))
        rows.append(row);ledger.append(identity)
    verified=0
    for entry in entries:
        assert _hash(Path(entry['source_path']))==entry['source_sha256']
        assert _hash(Path(entry['backup_path']))==entry['source_sha256'];verified+=1
    summary={'rule':RULE,'input_files':len(entries),'recovered':sum(counts.values()),
             'unrecoverable':len(entries)-sum(counts.values()),'formats':dict(counts),
             'originals_and_backups_verified_unchanged':verified,'record_publications':0,
             'existing_classifications_modified':False,'automatic_release':False}
    _save(destination/'index.json',{'summary':summary,'results':rows})
    _save(restricted/'recovery-ledger.json',ledger)
    _save(restricted/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))
    return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['manifest','destination','restricted']:parser.add_argument('--'+name,required=True)
    args=parser.parse_args();os.umask(0o077)
    run(args.manifest,args.destination,args.restricted)

if __name__=='__main__':main()
