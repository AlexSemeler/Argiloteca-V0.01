import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from argiloclay_intelligence.corpus import build
from argiloclay_intelligence.engine import Engine, REFUSAL, model_request, retrieve
from argiloclay_intelligence.invenio import Invenio, project
from argiloclay_intelligence.api import create_app


class Response(BytesIO):
    pass


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); voc = self.root / "vocab"; voc.mkdir()
        rows = [{"id": "kaolinite", "title": {"pt": "Caulinita", "en": "Kaolinite"}, "props": {"category": "species", "family": "kaolin_group"}},
                {"id": "smectite", "title": {"pt": "Esmectita", "en": "Smectite"}, "props": {"category": "group"}}]
        (voc / "argilominerais.jsonl").write_text("\n".join(json.dumps(x) for x in rows))
        (voc / "grupo_mineralogico.jsonl").write_text(json.dumps({"id": "kaolin_group", "title": {"pt": "Grupo da caulinita"}}))
        record = project({"id": "AM-1", "metadata": {"title": "Amostra caulinita", "description": "Descrição pública."}, "access": {"record": "public"}}, "https://example.org")
        snap = self.root / "records.jsonl"; snap.write_text(json.dumps(record))
        self.index = self.root / "index.sqlite3"; build(self.index, voc, records=snap)
        self.engine = Engine(self.index); self.http = create_app(self.engine).test_client()

    def test_bilingual_vocabulary_with_provenance(self):
        for question in ("O que é caulinita?", "What is kaolinite?"):
            result = self.engine.query(question, {"tipo_fonte": "vocabulario"})
            self.assertTrue(result["sources"])
            self.assertEqual(result["sources"][0]["term_id"], "kaolinite")
            self.assertEqual(len(result["sources"][0]["sha256"]), 64)

    def test_unknown_question_refuses_without_model(self):
        self.assertEqual(self.engine.query("Quem venceu o futebol?")["answer"], REFUSAL)

    def test_scope_mixing_does_not_answer_outside_corpus(self):
        self.assertEqual(self.engine.query("Qual presidente do Brasil caulinita?")["sources"], [])

    def test_filters_never_broaden_to_generic_literature(self):
        self.assertEqual(self.engine.query("caulinita", {"record_id": "MISSING"})["sources"], [])
        self.assertEqual(self.engine.query("caulinita", {"sample_code": "UNKNOWN"})["sources"], [])

    def test_record_source_scope(self):
        sources = self.engine.query("Mostre registros de caulinita")["sources"]
        self.assertTrue(sources); self.assertTrue(all(s["record_id"] == "AM-1" for s in sources))

    def test_malformed_input_and_unknown_filters(self):
        for payload in ([], {}, {"question": "a" * 2001}, {"question": "caulinita", "filters": []},
                        {"question": "caulinita", "filters": {"owner": "root"}},
                        {"question": "caulinita", "top_k": True}, {"question": "caulinita", "top_k": 13}):
            self.assertEqual(self.http.post("/api/v1/drx/query", json=payload).status_code, 400, payload)

    def test_timeout_keeps_cited_extractive_answer(self):
        def timeout(*args, **kwargs):
            raise TimeoutError()
        engine = Engine(self.index, use_model=True, opener=timeout)
        result = engine.query("caulinita")
        self.assertTrue(result["sources"]); self.assertEqual(result["generation_mode"], "extractive")

    def test_free_model_prose_and_fabricated_citations_are_rejected(self):
        for output in ('{"selected_ids":["E999"]}', '{"selected_ids":["E1"],"answer":"OURO 100%"}', "not-json", "[]", "null"):
            def opener(*args, **kwargs):
                return Response(json.dumps({"done_reason": "stop", "message": {"content": output}}).encode())
            result = Engine(self.index, use_model=True, opener=opener).query("caulinita")
            self.assertEqual(result["generation_mode"], "extractive")
            self.assertNotIn("OURO", result["answer"])

    def test_selected_text_is_exactly_the_input_to_model(self):
        captured = {}
        def opener(req, **kwargs):
            captured.update(json.loads(req.data))
            return Response(json.dumps({"done_reason": "stop", "message": {"content": '{"selected_ids":["E1"]}'}}).encode())
        result = Engine(self.index, use_model=True, opener=opener).query("caulinita")
        evidence = json.loads(captured["messages"][1]["content"])["evidence"][0]
        self.assertEqual(result["sources"][0]["excerpt"], evidence["text"])
        self.assertEqual(result["generation_mode"], "llm_evidence_selection")

    def test_model_empty_selection_refuses(self):
        def opener(*args, **kwargs):
            return Response(json.dumps({"done_reason": "stop", "message": {"content": '{"selected_ids":[]}'}}).encode())
        result = Engine(self.index, use_model=True, opener=opener).query("caulinita")
        self.assertEqual(result["answer"], REFUSAL)

    def test_context_budget_even_with_long_unicode(self):
        sources = [{"excerpt": "矿物 á " * 1000}] * 4
        payload, _ = model_request("á" * 2000, sources, "qwen3:1.7b")
        size = sum(len(m["content"].encode()) for m in payload["messages"])
        self.assertLessEqual(size + 200 + payload["options"]["num_predict"], 2048)

    def test_api_status_and_missing_index(self):
        self.assertEqual(self.http.get("/api/v1/drx/status").status_code, 200)
        http = create_app(Engine(self.root / "missing.sqlite3")).test_client()
        self.assertEqual(http.post("/api/v1/drx/query", json={"question": "caulinita"}).status_code, 503)

    def test_rest_fixed_origin_and_public_only(self):
        for base in ("http://example.org", "https://user:pw@example.org", "https://example.org/?token=x"):
            with self.assertRaises(ValueError):
                Invenio(base)
        with self.assertRaises(ValueError):
            Invenio("https://example.org", local_self_signed=True)
        client = Invenio("https://example.org", opener=lambda *a, **k: Response(json.dumps({"access": {"record": "restricted"}}).encode()))
        with self.assertRaises(ValueError):
            client.record("AM-1")
        with self.assertRaises(ValueError):
            client.record("../../drafts")

    def test_pdf_requires_explicit_rights(self):
        with self.assertRaises(ValueError):
            build(self.root / "new.sqlite3", self.root / "vocab", "untrusted.zip")


if __name__ == "__main__":
    unittest.main()
