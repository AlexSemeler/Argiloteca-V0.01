"""Offline negative checks for the XML parser available in homologation."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException


def classify(name, payload, expected_exception):
    try:
        fromstring(payload)
    except expected_exception as exc:
        return {"name": name, "result": "blocked", "exception": type(exc).__name__}
    except Exception as exc:  # pragma: no cover - evidence path
        return {"name": name, "result": "other-error", "exception": type(exc).__name__}
    return {"name": name, "result": "accepted", "exception": None}


def main():
    marker = Path("/tmp/argiloteca_xml_marker.txt")
    marker.write_text("harmless-xxe-marker", encoding="utf-8")
    checks = [
        classify(
            "xxe-file",
            f'<!DOCTYPE x [<!ENTITY e SYSTEM "file://{marker}">]><x>&e;</x>',
            DefusedXmlException,
        ),
        classify(
            "xxe-http",
            '<!DOCTYPE x [<!ENTITY e SYSTEM "http://127.0.0.1:9/no-request">]><x>&e;</x>',
            DefusedXmlException,
        ),
        classify(
            "entity-expansion",
            '<!DOCTYPE x [<!ENTITY a "1234567890"><!ENTITY b "&a;&a;&a;&a;&a;">]><x>&b;</x>',
            DefusedXmlException,
        ),
        classify("truncated", "<root><item></root>", ParseError),
        classify("invalid-encoding", b'<?xml version="1.0" encoding="UTF-8"?><x>\xff</x>', ParseError),
        classify(
            "unexpected-namespace",
            '<x xmlns="urn:argiloteca:unexpected"><item /></x>',
            ParseError,
        ),
    ]
    deep_payload = ("<n>" * 5000) + "value" + ("</n>" * 5000)
    checks.append(classify("deep-nesting-5000", deep_payload, ParseError))
    oversized_payload = "<x>" + ("a" * (2 * 1024 * 1024)) + "</x>"
    checks.append(classify("oversized-2mib", oversized_payload, ParseError))
    print(json.dumps({"parser": "defusedxml.ElementTree", "checks": checks}, indent=2))
    marker.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
