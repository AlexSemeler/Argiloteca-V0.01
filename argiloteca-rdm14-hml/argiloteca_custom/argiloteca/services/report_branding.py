"""Local, offline-capable institutional presentation for read-only DRX reports.

No network requests, record mutations or scientific calculations occur here.
CPAA is the spelling present in the official logo already shipped by Argiloteca.
"""
from base64 import b64encode
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def report_brand_assets():
    root = Path(__file__).resolve().parents[1] / 'static'
    logo = root / 'images/partners/cpaa.png'
    font = root / 'fonts/catamaran/catamaran-latin.woff2'
    return {
        'logo_data': 'data:image/png;base64,' + b64encode(logo.read_bytes()).decode('ascii'),
        'font_data': 'data:font/woff2;base64,' + b64encode(font.read_bytes()).decode('ascii'),
    }


def report_brand_header():
    """A local asset with a descriptive alternative and preserved proportions."""
    return ('<div class="report-brand"><img src="' + report_brand_assets()['logo_data']
        + '" width="144" height="84" alt="CPAA - Centro de Pesquisa em Argilas e Argilominerais"'
        + '><p>Argiloteca - CPAA<br>UFRGS - Petrobras</p></div>')


def report_styles():
    """Readable screen and A4 print hierarchy, repeated headers and page counters."""
    font = report_brand_assets()['font_data']
    return '''
@font-face{font-family:Catamaran;font-style:normal;font-weight:100 900;font-display:swap;src:url("''' + font + '''") format("woff2")}
:root{color-scheme:light;--report-brown:#704025;--report-text:#34291f;--report-muted:#66584a;--report-line:#c9bcae}
*{box-sizing:border-box}body{font:17px/1.6 Lato,Arial,sans-serif;color:var(--report-text);margin:0;background:#f4f1eb}
main{max-width:1120px;margin:auto;padding:32px 24px 56px;min-width:0}h1,h2,h3,h4{font-family:Catamaran,Arial,sans-serif;color:var(--report-brown);line-height:1.2;overflow-wrap:anywhere;text-wrap:balance}
h1{font-size:32px;margin:0 0 12px}h2{font-size:24px;margin:32px 0 12px}h3{font-size:20px;margin:24px 0 10px}p,li{max-width:75ch;orphans:3;widows:3}.meta,.note{color:var(--report-muted)}
a{color:var(--report-brown);text-underline-offset:.2em}a:hover{color:#4d2917}a:focus-visible{outline:2px solid var(--report-brown);outline-offset:3px}
.card{background:#fff;border:1px solid var(--report-line);padding:20px;margin:16px 0;min-width:0}.warning{background:#fff5e7;border:1px solid #aa7842}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.kv{min-width:0;overflow-wrap:anywhere}.kv strong{display:block;color:var(--report-brown)}
table{width:100%;border-collapse:collapse;background:#fff;table-layout:fixed;font-variant-numeric:tabular-nums}th,td{border:1px solid var(--report-line);padding:10px 9px;vertical-align:top;font-size:15px;overflow-wrap:anywhere}th{background:#ede6dc;color:var(--report-text);text-align:left}thead{display:table-header-group}tfoot{display:table-footer-group}tr{break-inside:avoid}h1,h2,h3,h4{break-after:avoid}section{overflow-wrap:anywhere}.report-brand{display:flex;align-items:center;gap:20px;border-bottom:1px solid var(--report-line);padding-bottom:16px;margin-bottom:24px}.report-brand img{width:144px;height:84px;object-fit:contain}.report-brand p{font-size:15px;margin:0;color:var(--report-muted)}
@media(max-width:600px){main{padding:20px 12px}h1{font-size:28px}.card{padding:14px}.grid{grid-template-columns:1fr}.report-brand{gap:12px}.report-brand img{width:110px;height:auto}th,td{font-size:14px;padding:7px 5px}}
@page{size:A4 portrait;margin:18mm 14mm 20mm;@bottom-left{content:"Argiloteca - CPAA";font:9pt Arial,sans-serif;color:#66584a}@bottom-right{content:counter(page) " / " counter(pages);font:9pt Arial,sans-serif;color:#66584a}}
@media print{body{background:white;font-size:11pt;line-height:1.5}main{max-width:none;padding:0}.card{border:0;padding:0;margin:0 0 18pt}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12pt}h1{font-size:24pt}h2{font-size:17pt;margin:20pt 0 8pt}h3{font-size:13pt}th,td{font-size:9.5pt;padding:6pt 5pt}.report-brand{break-inside:avoid}.report-brand p{font-size:10pt}.meta,.note{font-size:10pt}.warning{border:1px solid #aa7842;padding:10pt}.print-hint,button{display:none}thead{display:table-header-group}tr{break-inside:avoid;page-break-inside:avoid}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
'''
