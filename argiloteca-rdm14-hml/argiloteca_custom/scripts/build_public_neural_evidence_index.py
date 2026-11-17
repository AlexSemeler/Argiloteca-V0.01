#!/usr/bin/env python3
"""Publish auxiliary historical evidence only for verified anonymous public curves.

Original names, paths and private identity correspondence never enter the output.
Axis-incompatible historical predictions are withheld, not recomputed or relabeled.
"""
import argparse,hashlib,json,os,tempfile
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path


def read(path):return json.loads(Path(path).read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_public_index(snapshot,mapping,profiles_dir,xrdnet_summary,raw_dir):
    public=read(snapshot)['results'];identities={r['public_filename']:r for r in read(mapping)['entries']}
    profiles={}
    for p in Path(profiles_dir).glob('*/drx_ml_profile.json'):
        profile=read(p);sha=profile.get('source_sha256')
        if sha:profiles.setdefault(sha,[]).append((p,profile))
    summary=read(xrdnet_summary);model_rows=summary.get('rows',[])
    by_path={r.get('source_curve'):r for r in model_rows if r.get('source_curve')}
    by_curve_id={r.get('curve_id'):r for r in model_rows if r.get('curve_id')}
    counts=Counter();entries=[];seen=set()
    for row in public:
        filename=row.get('filename','');sha=row.get('metadata',{}).get('source_sha256')
        if not row.get('publication_eligible') or row.get('status')!='ok':raise ValueError('Non-public snapshot entry')
        if Path(filename).name!=filename or not filename.startswith('ARC-') or filename in seen:raise ValueError('Invalid anonymous identity')
        seen.add(filename);identity=identities.get(filename)
        if not identity or identity.get('derivative_sha256')!=sha or digest(Path(raw_dir)/filename)!=sha:raise ValueError('Public derivative provenance mismatch')
        md=row['metadata'];matches=profiles.get(identity.get('source_sha256'),[])
        valid=[]
        for path,profile in matches:
            extent=profile.get('original_range_two_theta',[])
            if (profile.get('original_points')==md.get('points') and len(extent)==2
                and abs(extent[0]-md['two_theta_start'])<1e-5 and abs(extent[1]-md['two_theta_end'])<1e-5):valid.append((path,profile))
        entry={'sample_id':row['sample_code'],'filename':filename,'source_sha256':sha,
            'diffractogram_id':'snapshot:'+hashlib.sha256(row['path'].encode()).hexdigest()[:20],
            'usage_policy':'auxiliary_not_confirmatory','candidates':[],'explain_bins':[],
            'profile':{'original_points':md['points'],'original_range_two_theta':[md['two_theta_start'],md['two_theta_end']]},
            'quality':{'metrics':{'original_points':md['points']},'warnings':[]},
            'warnings':['Triagem histórica experimental; não confirma identificação mineralógica.'],
            'match_keys':[]}
        if valid:
            path,profile=valid[0];model=by_path.get(profile.get('source_curve')) or by_curve_id.get(path.parent.name)
            if model:
                model_curve=Path(model.get('curve_path',''));profile_curve=Path(profile.get('outputs',{}).get('curve_standard_csv',''))
                if (model_curve.parent.name,model_curve.name)!=(profile_curve.parent.name,profile_curve.name):model=None
            entry['historical_profile_sha256']=digest(path)
            if model and model.get('status')=='ok':
                predictions=[]
                for prediction in model.get('top_predictions',[])[:6]:
                    label=prediction.get('label');value=prediction.get('probability')
                    if not isinstance(label,str) or not isinstance(value,(int,float)) or not 0<=value<=1:raise ValueError('Invalid historical prediction')
                    predictions.append({'label':label,'probability':value,'rank':prediction.get('rank')})
                entry['xrdnet']={'status':'ok','top_predictions':predictions,'labels':[],
                    'model':summary['model']['name'],'historical':True}
                entry['status']='historical_axis_compatible';counts['neural_predictions']+=1
                entry['warnings'].append('Escores do modelo histórico não são proporções minerais nem probabilidades calibradas.')
            else:entry['status']='historical_prediction_missing';counts['prediction_missing']+=1
        else:
            entry['status']='historical_axis_mismatch' if matches else 'historical_profile_missing'
            counts[entry['status']]+=1
            entry['warnings'].append('Previsões históricas retidas: eixo ou perfil de entrada incompatível com a curva pública atual; necessária nova inferência validada.')
        counts['entries']+=1;entries.append(entry)
    return {'schema_version':'argiloteca.drx.neural_evidence_index.v1',
       'generated_at':datetime.now(timezone.utc).isoformat(),
       'source':{'kind':'public_anonymous_historical_neural_evidence','usage_policy':'auxiliary_not_confirmatory',
          'matching_policy':'public_id_and_derivative_sha256_v1','snapshot_sha256':digest(snapshot),
          'model_summary_sha256':digest(xrdnet_summary),'model':summary['model']['name'],
          'model_metrics':summary.get('metrics',{}),
          'axis_policy':'same_original_sha256_point_count_and_declared_range; incompatible_predictions_withheld'},
       'counts':dict(counts),'entries':entries}


def atomic_write(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.neural-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(payload,out,ensure_ascii=False,separators=(',',':'),allow_nan=False);out.flush();os.fsync(out.fileno())
        os.chmod(name,0o644);os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','mapping','profiles-dir','xrdnet-summary','raw-dir','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();payload=build_public_index(args.snapshot,args.mapping,args.profiles_dir,args.xrdnet_summary,args.raw_dir)
    atomic_write(args.output,payload);print(json.dumps(payload['counts']))
