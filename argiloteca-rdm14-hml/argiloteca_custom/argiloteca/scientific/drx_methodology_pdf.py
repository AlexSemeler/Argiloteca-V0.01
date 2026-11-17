"""Generate a complete reading PDF from the same HTML used by the DRX guide."""
from pathlib import Path
from urllib.parse import unquote, urlparse


def methodology_pdf(rendered_guide, language='pt'):
    """Expand all source sections; use only packaged images, never remote resources."""
    from bs4 import BeautifulSoup
    from weasyprint import CSS, HTML, default_url_fetcher

    static = Path(__file__).resolve().parents[1] / 'static'
    soup = BeautifulSoup(rendered_guide, 'html.parser')
    article = soup.select_one('.argilo-drx-guide')
    for item in article.select('.argilo-drx-guide__breadcrumb, .argilo-drx-guide__actions, .argilo-drx-guide__top, svg'):
        item.decompose()
    for details in article.select('details'):
        details.name = 'section'
        details.attrs.pop('open', None)
        summary = details.find('summary', recursive=False)
        if summary:
            summary.name = 'h3'
    for img in article.select('img'):
        relative = img['src'].split('/argiloteca/static/', 1)[-1]
        path = (static / relative).resolve()
        if not path.is_relative_to(static.resolve()) or not path.is_file():
            raise ValueError('Invalid packaged methodology image')
        img['src'] = path.as_uri()
        img.attrs.pop('loading', None)
    def local_fetch(url, *args, **kwargs):
        parsed = urlparse(url)
        path = Path(unquote(parsed.path)).resolve()
        if parsed.scheme != 'file' or not path.is_relative_to(static.resolve()):
            raise ValueError('PDF resources must be packaged local files')
        return default_url_fetcher(url, *args, **kwargs)
    css = CSS(string='''
      @page { size: A4; margin: 19mm 17mm 20mm;
        @bottom-left { content: "Argiloteca · DRX"; color: #685340; font-size: 8pt; }
        @bottom-right { content: counter(page) " / " counter(pages); color: #685340; font-size: 8pt; }
      }
      body { font-family: "DejaVu Sans", sans-serif; color: #302b27; font-size: 10pt; line-height: 1.5; }
      h1,h2,h3,h4 { color: #6f4f34; line-height: 1.25; break-after: avoid; }
      h1 { font-size: 23pt; margin: 0 0 12pt; }
      h2 { font-size: 16pt; margin: 24pt 0 10pt; border-bottom: 1pt solid #d7cabe; padding-bottom: 7pt; }
      h3 { font-size: 11pt; margin: 16pt 0 8pt; }
      h4 { font-size: 10.5pt; margin: 14pt 0 7pt; }
      p { margin: 0 0 9pt; orphans: 3; widows: 3; }
      a { color: #6f4f34; text-decoration: underline; overflow-wrap: anywhere; }
      figure { margin: 10pt 0 14pt; break-inside: avoid; }
      img { max-width: 100%; width: auto; height: auto; max-height: 125pt; object-fit: contain; }
      figcaption { font-size: 8pt; color: #685340; margin-top: 5pt; }
      figcaption strong, .argilo-drx-figure__credit { display: block; }
      .argilo-drx-guide__hero-image img { max-height: 110pt; }
      .argilo-drx-guide__source-label { font-size: 9pt; }
      .argilo-drx-guide__notice { padding: 10pt; background: #fbf7f0; border: .6pt solid #d7cabe; margin: 16pt 0; }
      .argilo-drx-guide__index { break-after: page; }
      .argilo-drx-guide__index nav a { display: block; text-decoration: none; margin: 6pt 0; }
      .argilo-drx-guide__index nav a::after { content: leader('.') target-counter(attr(href), page); }
      .argilo-drx-guide__source { margin: 15pt 0; padding-top: 5pt; }
      .argilo-drx-guide__equation { padding: 12pt; background: #f5f0e8; margin: 12pt 0; }
      .argilo-drx-guide__equation strong { display: block; font-size: 16pt; margin-bottom: 6pt; }
      table { width: 100%; border-collapse: collapse; font-size: 8.5pt; margin: 12pt 0; table-layout: fixed; }
      caption { text-align: left; font-weight: bold; color: #6f4f34; margin-bottom: 6pt; }
      thead { display: table-header-group; }
      tr { break-inside: avoid; }
      th,td { text-align: left; vertical-align: top; border-bottom: .5pt solid #d7cabe; padding: 6pt; overflow-wrap: anywhere; }
      thead th { background: #f5f0e8; }
      tbody th { font-weight: normal; }
      dt { font-weight: bold; } dd { margin: 2pt 0 8pt; }
      li { margin-bottom: 7pt; orphans: 3; widows: 3; }
    ''')
    markup = '<!doctype html><html lang="' + ('en' if language == 'en' else 'pt') + '"><head><meta charset="utf-8"></head><body>' + str(article) + '</body></html>'
    return HTML(string=markup, url_fetcher=local_fetch).write_pdf(stylesheets=[css])
