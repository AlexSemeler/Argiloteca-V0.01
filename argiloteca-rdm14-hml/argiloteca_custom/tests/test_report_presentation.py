"""Report presentation must not lose zeros, execute markup, or need remote assets."""
from copy import deepcopy
from argiloteca.services.drx_report import _peak_summary, render_drx_technical_report_html
from argiloteca.services.drx_selection_report import _compact_peak, render_drx_selection_report_html
from argiloteca.services.report_branding import report_brand_assets, report_styles


def test_peak_exports_preserve_zero_and_full_precision():
    source = {'peak_index':0,'two_theta':0.0,'d_angstrom':0.0,'relative_intensity':0.0,'height':44,
        'center_2theta':88,'d':99,'intensity_relative':77,'fwhm':0.123456789}
    for actual in [_peak_summary([source])[0], _compact_peak(source)]:
        for key in ['two_theta','d_angstrom','relative_intensity','peak_index']:
            assert actual[key] == 0
        assert actual['fwhm'] == source['fwhm']


def test_technical_print_is_safe_offline_and_does_not_mutate_payload():
    report = {'input':{'filename':'<script>private()</script>.raw'},'peaks':[{'two_theta':0}],
        'limitations':['<img onerror="x">'], 'summary':{'candidate_count':0}}
    before = deepcopy(report)
    html = render_drx_technical_report_html(report)
    assert report == before
    assert '<script>private()' not in html and '&lt;script&gt;' in html
    assert '<img onerror' not in html
    assert 'data:image/png;base64,' in html and 'data:font/woff2;base64,' in html
    assert 'CPAA - Centro de Pesquisa' in html and 'scope="col"' in html
    assert 'content:counter(page)' in html and 'display:table-header-group' in html


def test_selection_zero_score_and_untrusted_values_survive_escaped():
    report={'ngc_summary':{'best_candidates':[{'score':0,'mineral_candidate':'<b>Argila</b>'}]}}
    before=deepcopy(report)
    html=render_drx_selection_report_html(report)
    assert report==before and '<td>0</td>' in html and '&lt;b&gt;Argila&lt;/b&gt;' in html
    assert '<th scope="col">' in html


def test_brand_assets_are_local_and_print_text_is_legible():
    assets=report_brand_assets()
    assert assets['logo_data'].startswith('data:image/png;base64,iVBOR')
    assert assets['font_data'].startswith('data:font/woff2;base64,')
    css=report_styles()
    assert 'font-size:11pt' in css and 'font-size:9.5pt' in css
    assert '#704025' in css and 'break-inside:avoid' in css
