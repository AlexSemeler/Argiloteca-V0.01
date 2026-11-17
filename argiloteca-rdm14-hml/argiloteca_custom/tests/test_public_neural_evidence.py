import importlib.util,json,hashlib
from pathlib import Path
import pytest
from argiloteca.services.neural_evidence import neural_evidence_for_diffractogram


def index(tmp_path):
 p=tmp_path/'neural.json';p.write_text(json.dumps({'source':{'matching_policy':'public_id_and_derivative_sha256_v1'},'entries':[
  {'diffractogram_id':'snapshot:n','source_sha256':'sha-n','sample_id':'same','status':'historical_axis_compatible'},
  {'diffractogram_id':'snapshot:g','source_sha256':'sha-g','sample_id':'same','status':'historical_axis_mismatch','warnings':['retained'],'candidates':[]}]}));return p

def test_exact_curve_and_digest_prevent_wrong_ngc_treatment(tmp_path):
 p=index(tmp_path)
 for id,sha in [('snapshot:n','sha-n'),('snapshot:g','sha-g')]:
  r=neural_evidence_for_diffractogram(id,metadata={'source_sha256':sha,'sample_code':'same'},path=p)
  assert r['success'] and r['evidence']['diffractogram_id']==id
 for id,sha in [('snapshot:n','sha-g'),('snapshot:unknown','sha-n'),('snapshot:n',None)]:
  assert not neural_evidence_for_diffractogram(id,metadata={'source_sha256':sha,'sample_code':'same'},path=p)['success']

def test_package_requires_exact_unique_public_anonymous_file_digest(tmp_path):
 p=index(tmp_path)
 assert neural_evidence_for_diffractogram('package',metadata={'source_sha256':'sha-n'},path=p)['success']
 assert not neural_evidence_for_diffractogram('private-name',metadata={'filename':'original.raw'},path=p)['success']

def test_axis_mismatch_is_visible_without_invented_predictions(tmp_path):
 r=neural_evidence_for_diffractogram('snapshot:g',metadata={'source_sha256':'sha-g'},path=index(tmp_path))
 assert r['success'] and r['evidence']['status']=='historical_axis_mismatch' and 'xrdnet' not in r['evidence']

@pytest.fixture
def builder(tmp_path):
 script=Path(__file__).resolve().parents[1]/'scripts/build_public_neural_evidence_index.py'
 spec=importlib.util.spec_from_file_location('public_neural_builder',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 raw=tmp_path/'raw';raw.mkdir();(raw/'ARC-TEST_N.raw').write_bytes(b'public-anonymous-curve')
 sha=hashlib.sha256(b'public-anonymous-curve').hexdigest()
 snapshot=tmp_path/'snapshot.json';snapshot.write_text(json.dumps({'results':[{'filename':'ARC-TEST_N.raw','sample_code':'ARC-TEST','path':'/public/ARC-TEST_N.raw','publication_eligible':True,'status':'ok','metadata':{'source_sha256':sha,'points':3,'two_theta_start':2,'two_theta_end':3}}]}))
 mapping=tmp_path/'private.json';mapping.write_text(json.dumps({'entries':[{'public_filename':'ARC-TEST_N.raw','derivative_sha256':sha,'source_sha256':'original-sha','source_path':'private-researcher/original.raw'}]}))
 profiles=tmp_path/'profiles';profile=profiles/'private-researcher';profile.mkdir(parents=True);(profile/'drx_ml_profile.json').write_text(json.dumps({'source_sha256':'original-sha','source_curve':'private-researcher/original.raw','original_points':3,'original_range_two_theta':[2,3],'outputs':{'curve_standard_csv':'/private/private-researcher/curve_standard.csv'}}))
 summary=tmp_path/'model.json';summary.write_text(json.dumps({'model':{'name':'historical-model'},'rows':[{'curve_id':'private-researcher','curve_path':'/private/private-researcher/curve_standard.csv','status':'ok','top_predictions':[{'label':'kaolinite','probability':0.6,'rank':1}]}]}))
 return module,dict(snapshot=snapshot,mapping=mapping,profiles_dir=profiles,xrdnet_summary=summary,raw_dir=raw)

def test_builder_only_publishes_anonymous_verified_derivatives(builder):
 module,args=builder;payload=module.build_public_index(**args)
 assert payload['counts']['neural_predictions']==1
 text=json.dumps(payload);assert 'private-researcher' not in text and 'original-sha' not in text and 'source_path' not in text
 assert payload['entries'][0]['xrdnet']['top_predictions'][0]['label']=='kaolinite'

def test_builder_withholds_historical_predictions_for_changed_axis(builder):
 module,args=builder;p=next(args['profiles_dir'].glob('*/drx_ml_profile.json'));d=json.loads(p.read_text());d['original_range_two_theta']=[5,6];p.write_text(json.dumps(d))
 payload=module.build_public_index(**args);assert 'xrdnet' not in payload['entries'][0];assert payload['counts']['historical_axis_mismatch']==1

def test_builder_rejects_modified_anonymous_file_instead_of_reusing_old_result(builder):
 module,args=builder;(args['raw_dir']/'ARC-TEST_N.raw').write_bytes(b'changed')
 with pytest.raises(ValueError,match='provenance'):module.build_public_index(**args)
