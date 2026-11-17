"""Read accepted analytical complements inside authorized native record pages."""
import json
import re
import sqlite3

from flask import current_app, request

from . import enrichment as e
from .analytics import doi_of, work_ids


def record_complements(rid):
    # The native view checks access before rendering this template. Never expose
    # analytical values in draft previews or through a separate public endpoint.
    if not isinstance(rid,str) or not re.fullmatch(r'[a-z0-9]+-[a-z0-9]+',rid):return None
    if request.path.rstrip('/')!='/records/'+rid:return None
    version=e.head()
    if not version:return None
    try:
        job=e.checked_version(version)
        with e.store(version) as c:
            accepted=c.execute('SELECT * FROM accepted WHERE rid=?',(rid,)).fetchone()
            if not accepted:return None
            live=e.native(accepted['uid'])
            if not live or live[1]!='P' or live[0].get('id')!=rid:return None
            ids=work_ids(live[0]);doi=doi_of(live[0])
            if ids:
                if len(ids)!=1 or accepted['oa_id'].rsplit('/',1)[-1] not in ids:return None
                if doi and accepted['doi'] and accepted['doi']!=doi:return None
            elif not doi or doi!=accepted['doi']:return None
            payload=json.loads(accepted['payload'])
            return {'payload':payload,'version':version,'applied_at':job.result['applied_at']}
    except (ValueError,sqlite3.Error,KeyError,TypeError):
        current_app.logger.warning('OpenAlex accepted complements unavailable for record %s',rid)
        return None


def configure(app):
    @app.context_processor
    def helpers():
        return {'argilo_openalex_complements':record_complements}
