"""Native publication gate for anonymous, complete N/G/C RAW datasets.

Draft saving is deliberately unrestricted by this component. No publication or
record rewriting is performed here. The same gate covers UI and API publishing.
"""
import hashlib
from invenio_drafts_resources.services.records.components import ServiceComponent
from marshmallow import ValidationError
from argiloteca_drx_core.raw_lifecycle import validate_public_raw_files, PUBLIC_FILENAME
from argiloteca_drx_core.parser_limits import MAX_CURVE_BYTES


def validate_raw_metadata(custom_fields, filenames, sample_codes, file_hashes=None):
    """RAW references must resolve to attached anonymous files, not local paths."""
    def walk(value):
        if isinstance(value, dict):
            raw = value.get('arquivo_raw')
            if isinstance(raw, str) and raw in filenames:
                sample = PUBLIC_FILENAME.fullmatch(raw).group(1).upper()
                if value.get('codigo_amostra') and value['codigo_amostra'] != sample:
                    raise ValueError('RAW and sample links disagree / O vínculo entre RAW e amostra não corresponde.')
                if file_hashes and value.get('raw_sha256') and str(value['raw_sha256']).lower() != file_hashes[raw]:
                    raise ValueError('RAW metadata hash must match the anonymous file / Atualize o hash do RAW anonimizado.')
            for key, child in value.items():
                if key == 'arquivo_raw' and child:
                    if not isinstance(child, str) or child not in filenames:
                        raise ValueError('RAW metadata must reference an attached anonymous file / Vincule o RAW anonimizado anexado.')
                if sample_codes and key == 'codigo_amostra' and child not in sample_codes:
                    raise ValueError('Sample metadata must use the anonymous sample code / Use o código anonimizado da amostra.')
                yield from walk(child)
        elif isinstance(value, list):
            for child in value: yield from walk(child)
    list(walk(custom_fields or {}))


class RawTrioPublicationComponent(ServiceComponent):
    """Run before native file-copy components, including on published revisions."""
    def publish(self, identity, draft=None, record=None, **kwargs):
        files = draft.files
        raw_names = []
        file_hashes = {}
        def raw_files():
            total = 0
            if not files.enabled:
                return
            for key in files.entries:
                file_record = files[key]
                obj = file_record.object_version
                instance = obj.file if obj else None
                if instance is None:
                    if key.lower().endswith('.raw'):
                        raise ValueError('RAW transfer must be complete / Conclua o envio do RAW.')
                    continue
                with instance.storage().open('rb') as stream:
                    prefix = stream.read(8)
                    if not key.lower().endswith('.raw') and not prefix.startswith((b'RAW ', b'RAW1.', b'RAW2', b'RAW4')):
                        continue
                    content = prefix + stream.read(MAX_CURVE_BYTES + 1 - len(prefix))
                total += len(content)
                if len(content) > MAX_CURVE_BYTES or total > 512*1024*1024:
                    raise ValueError('RAW validation limit exceeded / Limite de validação RAW excedido.')
                raw_names.append(key)
                file_hashes[key] = hashlib.sha256(content).hexdigest()
                yield key, content
        try:
            codes = validate_public_raw_files(raw_files())
            validate_raw_metadata(draft.get('custom_fields') or {}, set(raw_names), set(codes), file_hashes)
        except ValueError as exc:
            raise ValidationError(str(exc), field_name='files') from exc
