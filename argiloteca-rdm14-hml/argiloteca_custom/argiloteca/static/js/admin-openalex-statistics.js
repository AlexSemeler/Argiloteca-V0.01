/* Native Invenio administration charts. React/Recharts are supplied by the
   verified, data-free Data 1.0.11 prebuilt runtime; no CDN or record writes. */
(function () {
  'use strict';
  const input = document.getElementById('oa-statistics-data');
  if (!input) return;
  const snapshot = JSON.parse(input.textContent);
  const pt = snapshot.locale === 'pt';
  const t = (a, b) => pt ? a : b;
  const format = new Intl.NumberFormat(pt ? 'pt-BR' : 'en-US');
  const unknown = t('Não informado', 'Not provided');
  const sourceNames = {
    journal: t('Periódicos', 'Journals'),
    'book series': t('Séries de livros', 'Book series'),
    'ebook platform': t('Plataformas de livros', 'Book platforms'),
    repository: t('Repositórios', 'Repositories'),
    conference: t('Eventos', 'Conferences'),
    other: t('Outros tipos', 'Other types'),
  };
  function filter(name, value) {
    const form = document.getElementById('oa-statistics-filters');
    if (name === 'year') {
      form.elements.year_from.value = value;
      form.elements.year_to.value = value;
    } else form.elements[name].value = value;
    form.requestSubmit();
  }
  function fail(plot) {
    const message = plot.querySelector('[role="status"]');
    if (message) message.textContent = t('Gráfico indisponível. Consulte os valores na tabela abaixo.', 'Chart unavailable. See values in the table below.');
    plot.closest('section').querySelector('details').open = true;
  }
  if (typeof CodexDataAppRuntime === 'undefined') {
    document.querySelectorAll('[data-oa-chart]').forEach(fail);
    return;
  }
  const React = CodexDataAppRuntime.modules.react;
  const {createRoot} = CodexDataAppRuntime.modules['react-dom/client'];
  const {ResponsiveContainer, BarChart, Bar, LineChart, Line, CartesianGrid,
    XAxis, YAxis, Tooltip, LabelList, ReferenceLine} = CodexDataAppRuntime.modules.recharts;
  const h = React.createElement;
  const ink = '#694c33', accent = '#a15d27', grid = '#ded9d2';
  const labelOf = (row, kind) => {
    if (row.label === null || row.label === '') return unknown;
    return kind === 'source_types' ? (sourceNames[row.label] || String(row.label)) : String(row.label);
  };
  function PointTooltip({active, payload, kind}) {
    if (!active || !payload || !payload.length) return null;
    const row = payload[0].payload;
    return h('div', {className: 'oa-chart-tooltip', role: 'status'},
      h('strong', null, labelOf(row, kind)),
      h('p', null, format.format(row.n) + ' ' + (kind === 'citations' ? t('citações', 'citations') : t('publicações', 'publications'))));
  }
  function Chart({kind, original, plot}) {
    const [expanded, setExpanded] = React.useState(false);
    const [width, setWidth] = React.useState(plot.clientWidth);
    React.useEffect(() => {
      const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
      observer.observe(plot);
      plot.closest('section').querySelector('details').open = false;
      return () => observer.disconnect();
    }, []);
    const temporal = kind === 'years';
    const distribution = kind === 'fwci';
    const knownYears = temporal ? original.filter(row => Number.isInteger(row.label)) : [];
    const missingYears = temporal ? original.filter(row => row.label === null).reduce((sum, row) => sum + row.n, 0) : 0;
    let rows;
    if (temporal && knownYears.length) {
      const byYear = new Map(knownYears.map(row => [row.label, row.n]));
      const first = Math.min(...byYear.keys()), last = Math.max(...byYear.keys());
      const start = expanded ? first : Math.max(first, last - 29);
      rows = Array.from({length: last - start + 1}, (_, i) => ({label: start + i, n: byYear.get(start + i) || 0}));
    } else rows = temporal ? [] : original.slice(0, expanded ? 15 : (kind === 'citations' ? 5 : 6));
    if (distribution) rows = original;
    // Recharts omits null categories; retain missing metadata explicitly.
    rows = rows.map(row => ({...row, displayLabel: labelOf(row, kind)}));
    const canExpand = distribution ? false : temporal ? knownYears.length && Math.max(...knownYears.map(r => r.label)) - Math.min(...knownYears.map(r => r.label)) >= 30 : original.length > rows.length;
    const interactive = ['subject', 'keyword', 'primary_topic', 'subfield', 'field', 'domain'].includes(kind);
    const totalNote = temporal
      ? (rows.length ? `${rows[0].label}–${rows[rows.length - 1].label}` : unknown) + (missingYears ? ` · ${format.format(missingYears)} ${t('sem ano', 'without year')}` : '')
      : t('Exibindo ', 'Showing ') + rows.length + ' / ' + original.length;
    const tools = h('div', {className: 'oa-chart-tools'},
      h('p', null, totalNote),
      (canExpand || expanded) && h('button', {type: 'button', 'aria-expanded': expanded, onClick: () => setExpanded(!expanded)},
        temporal ? (expanded ? t('Últimos 30 anos', 'Last 30 years') : t('Série completa', 'Complete series')) : (expanded ? t('Mostrar menos', 'Show fewer') : t('Mostrar até 15', 'Show up to 15'))));
    if (!rows.length) return h('div', null, tools, h('p', {className: 'oa-chart-empty'}, t('Ano não informado. Consulte a tabela.', 'Year not provided. See the table.')));
    const tooltip = h(Tooltip, {content: h(PointTooltip, {kind}), cursor: {fill: '#f3ede5'}, isAnimationActive: false, allowEscapeViewBox: {x: false, y: false}});
    const chart = distribution ? h(BarChart, {data: original, margin:{top:36,right:24,bottom:18,left:0},accessibilityLayer:true,barSize:14},
      h(CartesianGrid,{stroke:grid,vertical:false}),
      h(XAxis,{dataKey:'x',type:'number',domain:[0,11],ticks:[0,1,2,5,10.5],tickFormatter:x=>x===10.5?'≥10':x,tick:{fill:'#4c443b',fontSize:13}}),
      h(YAxis,{allowDecimals:false,width:45,tick:{fill:'#4c443b',fontSize:13}}),tooltip,
      h(ReferenceLine,{x:1,stroke:accent,strokeDasharray:'4 3',label:{value:t('Referência 1','Reference 1'),position:'top',fill:ink,fontSize:13}}),
      h(Bar,{dataKey:'n',fill:ink,isAnimationActive:false})) : temporal ? h(LineChart, {data: rows, margin: {top: 15, right: 28, bottom: 10, left: 0}, accessibilityLayer: true,
      onClick: state => {const year = state && state.activeLabel; if (year !== null && year !== undefined && Number.isInteger(Number(year))) filter('year', Number(year));}},
      h(CartesianGrid, {stroke: grid, vertical: false}),
      h(XAxis, {dataKey: 'label', type: 'number', domain: ['dataMin', 'dataMax'], allowDecimals: false, tick: {fill: '#4c443b', fontSize: 13}, minTickGap: 28, tickLine: false, axisLine: {stroke: grid}}),
      h(YAxis, {allowDecimals: false, tickFormatter: n => format.format(n), width: width < 500 ? 45 : 62, tick: {fill: '#4c443b', fontSize: 13}, tickLine: false, axisLine: false}),
      tooltip, h(Line, {type: 'linear', dataKey: 'n', stroke: accent, strokeWidth: 2.5, dot: rows.length < 40 ? {r: 2.5, fill: accent} : false, activeDot: {r: 5}, isAnimationActive: false}))
      : h(BarChart, {data: rows, layout: 'vertical', margin: {top: 4, right: 58, bottom: 4, left: 0}, barSize: 15, accessibilityLayer: true},
        h(CartesianGrid, {stroke: grid, horizontal: false}),
        h(XAxis, {type: 'number', domain: [0, 'dataMax'], allowDecimals: false, tickFormatter: n => format.format(n), minTickGap: 30, tick: {fill: '#4c443b', fontSize: 12}, axisLine: {stroke: grid}, tickLine: false}),
        h(YAxis, {type: 'category', dataKey: 'displayLabel', width: width < 480 ? 116 : 185, interval: 0,
          tickFormatter: (value) => {const full = String(value); const limit = width < 480 ? 13 : 24; return full.length > limit ? full.slice(0, limit - 1) + '…' : full;},
          tick: {fill: '#4c443b', fontSize: 13}, tickLine: false, axisLine: false}),
        tooltip,
        h(Bar, {dataKey: 'n', fill: ink, radius: [0, 3, 3, 0], isAnimationActive: false,
          cursor: interactive ? 'pointer' : 'default', onClick: interactive ? row => {const value = (row.payload || row).label; if (value) filter(['subject','keyword'].includes(kind)?'subject':kind, ['subject','keyword'].includes(kind)?String(value):(row.payload||row).id);} : undefined},
          h(LabelList, {dataKey: 'n', position: 'right', formatter: n => format.format(n), fill: '#302a24', fontSize: 13})));
    return h('div', {'data-reviewed-rows': kind}, tools,
      h(ResponsiveContainer, {width: '100%', height: temporal || distribution ? 290 : Math.max(170, rows.length * 42 + 32)}, chart));
  }
  class Boundary extends React.Component {
    constructor(props) {super(props); this.state = {error: false};}
    static getDerivedStateFromError() {return {error: true};}
    componentDidCatch() {this.props.plot.closest('section').querySelector('details').open = true;}
    render() {return this.state.error ? h('p', {role: 'status'}, t('Gráfico indisponível. Consulte a tabela abaixo.', 'Chart unavailable. See the table below.')) : this.props.children;}
  }
  document.querySelectorAll('[data-oa-chart]').forEach(plot => {
    try {
      const kind = plot.dataset.oaChart;
      createRoot(plot).render(h(Boundary, {plot}, h(Chart, {kind, original: snapshot.data[kind], plot})));
    } catch (error) {fail(plot);}
  });
})();
