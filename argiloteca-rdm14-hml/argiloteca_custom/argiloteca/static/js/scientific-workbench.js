/* Presentation layer for the existing DRX controller. No scientific API or calculation. */
(function () {
  'use strict';
  const escape = function (value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  const number = function (value, digits) { return value != null && Number.isFinite(Number(value)) ? Number(value).toLocaleString(window.argiloLocale || 'pt-BR', { maximumFractionDigits: digits == null ? 3 : digits }) : '—'; };
  function table(headings, rows) {
    return '<div class="awb-data-scroll"><table class="awb-data-table"><thead><tr>' + headings.map(function (h) { return '<th scope="col">' + escape(h) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.map(function (row) { return '<tr>' + row.map(function (cell) { return '<td>' + escape(cell) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
  }
  function referencePilot(pilot) {
    if (!pilot || pilot.status === 'disabled') return '';
    const t = function (value) { return escape(window.argiloT(value)); };
    const title = '<h3>' + t('Referências AMCSD e COD · piloto') + '</h3>';
    if (!pilot.available) return '<section class="awb-reference-pilot">' + title + '<p role="status">' + t('Referências indisponíveis. A curva e a comparação permanecem disponíveis.') + '</p></section>';
    const candidates = (pilot.candidates || []).map(function (candidate) {
      const link = /^https:\/\/(?:(?:www\.)?(?:crystallography\.net|rruff\.net)|rruff\.geo\.arizona\.edu)\//.test(candidate.source_url || '')
        ? '<a href="' + escape(candidate.source_url) + '" target="_blank" rel="noopener noreferrer">' + t('Abrir referência original') + '</a>' : '';
      return '<details class="awb-reference-detail"><summary>' + escape(candidate.mineral_name) + ' · ' + escape(candidate.source) + ' ' + escape(candidate.source_id) + ' · ' + escape(candidate.matched_peak_count) + '/' + escape(candidate.observable_reference_peak_count) + ' ' + t('reflexões compatíveis') + '</summary>'
        + '<p>' + t('Padrão calculado de estrutura ideal; não representa tratamento N/G/C.') + '</p>'
        + table([window.argiloT('2θ observado (°)'), window.argiloT('2θ referência (°)'), 'd (Å)', 'hkl'], (candidate.matches || []).map(function (match) { return [number(match.observed_two_theta), number(match.reference_two_theta), number(match.reference_d_angstrom), match.hkl || '—']; }))
        + '<p>' + escape(candidate.citation) + '</p><p>' + link + '</p>'
        + ((candidate.variants || []).length ? '<p class="awb-small">' + t('Outras estruturas da mesma hipótese, sem contar como evidência independente:') + ' ' + escape(candidate.variants.join('; ')) + '</p>' : '')
        + '<p class="awb-small">' + t('Picos observados não explicados por esta referência:') + ' ' + escape((candidate.unmatched_observed_peaks || []).map(function (v) { return number(v); }).join('; ') || '—') + '</p></details>';
    }).join('');
    return '<section class="awb-reference-pilot" data-reference-pilot="' + escape(pilot.status) + '">' + title
      + '<p class="awb-notice">' + t('Evidência auxiliar em avaliação. Não altera a classificação existente e não confirma identificação mineralógica.') + '</p>'
      + '<p class="awb-small">' + t('Versão das referências:') + ' ' + escape(pilot.index_version) + '</p>'
      + (pilot.wavelength_assumed ? '<p class="awb-notice">' + t('Comprimento de onda assumido: Cu Kα1, 1,5406 Å. Verifique os metadados da coleta.') + '</p>' : '')
      + (candidates || '<p>' + t('Não conclusivo: nenhuma referência do piloto apresentou duas reflexões compatíveis. Isso não indica ausência do mineral.') + '</p>')
      + '<p class="awb-small">' + t('A cobertura é limitada. Orientação, hidratação e interestratificação exigem avaliação com o preparo e o contexto da amostra.') + '</p></section>';
  }
  window.ArgiloScientificWorkbench = {
    connect: function (root, api) {
      const query = function (selector) { return root.querySelector(selector); };
      const all = function (selector) { return Array.from(root.querySelectorAll(selector)); };
      const icon = function (name) { const template = query('template[data-awb-icon="' + name + '"]'); return template ? template.innerHTML : ''; };
      const workspace = query('.argilo-workbench');
      if (!workspace) return null;
      const grid = query('.awb-grid');
      let state = { activeId: null, tab: 'peaks', mobile: 'chart', evidence: true, inspector: true };
      let previouslyHadItems = false;
      let relationKey = null;
      let relationRequest = null;
      const relationText = function (pt, en) { return document.documentElement.lang.startsWith('pt') ? pt : en; };
      function relatedRecords(active) {
        const pane = query('[data-awb-content="records"]');
        if (!pane) return;
        const matches = (active.packageSimilarity && active.packageSimilarity.matches) || [];
        const rawId = (active.metadata || {}).raw_id || (active.id.startsWith('linked:') ? active.id.slice(7) : '');
        const ids = Array.from(new Set([rawId].concat(matches.map(function (m) { return m.raw_id; })).filter(function (id) { return /^[a-f0-9]{24}$/.test(id || ''); }))).slice(0, 20);
        const key = active.id + ':' + ids.join(',');
        if (relationKey === key) return;
        relationKey = key;
        if (relationRequest) relationRequest.abort();
        const heading = '<h3>' + escape(relationText('Registros relacionados', 'Related records')) + '</h3>';
        if (!ids.length) {
          pane.innerHTML = heading + '<p>' + escape(relationText('Este arquivo ainda não possui vínculo persistido com o acervo. Selecione um RAW do acervo ou consulte os resultados da comparação.', 'This file has no persisted repository association. Select a repository RAW or inspect the comparison results.')) + '</p>';
          return;
        }
        pane.innerHTML = heading + '<p role="status">' + escape(relationText('Consultando os títulos e vínculos do acervo…', 'Loading repository titles and associations…')) + '</p>';
        relationRequest = new AbortController();
        fetch('/scientific/drx/related-records?raw_ids=' + encodeURIComponent(ids.join(',')), {credentials: 'same-origin', signal: relationRequest.signal, headers: {Accept: 'application/json'}})
          .then(function (response) { if (!response.ok) throw new Error('HTTP ' + response.status); return response.json(); })
          .then(function (payload) {
            if (relationKey !== key) return;
            const records = new Map();
            (payload.items || []).forEach(function (row) {
              if (row.raw_id === rawId) active.metadata.record_links = row.record_links;
              matches.filter(function (match) { return match.raw_id === row.raw_id; }).forEach(function (match) { match.record_links = row.record_links; });
              (row.record_links || []).forEach(function (link) {
                if (!/^[a-z0-9]{5}-[a-z0-9]{5}$/i.test(link.record_id)) return;
                if (!records.has(link.record_id)) records.set(link.record_id, {title: link.title, files: []});
                records.get(link.record_id).files.push({filename: row.filename, state: link.state, direct: row.raw_id === rawId});
              });
            });
            const list = Array.from(records.entries()).map(function (entry) {
              const pid = entry[0], record = entry[1];
              const files = record.files.map(function (file) { return '<li><strong>' + escape(file.filename) + '</strong> · ' + escape(file.direct ? relationText('RAW selecionado', 'Selected RAW') : relationText('RAW comparado', 'Compared RAW')) + ' · ' + escape(file.state === 'confirmed' ? relationText('Vínculo confirmado', 'Confirmed association') : relationText('Vínculo pendente de curadoria', 'Association awaiting curation')) + '</li>'; }).join('');
              return '<article class="awb-related-record"><h4><a href="/records/' + encodeURIComponent(pid) + '">' + escape(record.title || pid) + '</a></h4><p>' + escape(relationText('Identificador do registro', 'Record identifier')) + ': ' + escape(pid) + '</p><ul>' + files + '</ul><a class="ui button" href="/analises/' + encodeURIComponent(pid) + '">' + escape(relationText('Ver análises do registro', 'View record analyses')) + '</a></article>';
            }).join('');
            pane.innerHTML = heading + '<p>' + escape(relationText('Títulos dos registros associados aos arquivos desta comparação. Similaridade não confirma identificação mineralógica ou origem da amostra.', 'Titles of records associated with files in this comparison. Similarity does not confirm mineralogical identification or sample provenance.')) + '</p>' + (list || '<p role="status">' + escape(relationText('Nenhum registro relacionado disponível para os arquivos consultados. Acesso e curadoria dos vínculos são respeitados.', 'No related record is available for these files. Association access and curation rules apply.')) + '</p>');
            if (state.tab === 'records' && window.matchMedia('(max-width: 767px)').matches) {
              (pane.querySelector('.awb-related-record') || pane).scrollIntoView({block: 'nearest'});
            }
            persist();
          }).catch(function (error) {
            if (error.name === 'AbortError' || relationKey !== key) return;
            pane.innerHTML = heading + '<p role="alert">' + escape(relationText('Não foi possível consultar os registros relacionados. Confira sua sessão e tente novamente.', 'Related records could not be loaded. Check your session and try again.')) + '</p><button class="ui button" type="button" data-awb-records-retry>' + escape(relationText('Tentar novamente', 'Try again')) + '</button>';
          });
      }

      function persist() { api.save().catch(function () {}); }
      function resizePlot() {
        const chart = query('[data-role="plotly-chart"]');
        if (chart && chart._fullLayout && !chart.hidden && chart.getClientRects().length && window.Plotly) window.Plotly.Plots.resize(chart).catch(function () {});
      }
      function chooseMobile(pane) {
        state.mobile = pane;
        grid.dataset.mobilePane = pane;
        all('[data-awb-mobile]').forEach(function (button) { button.setAttribute('aria-selected', String(button.dataset.awbMobile === pane)); button.tabIndex = button.dataset.awbMobile === pane ? 0 : -1; });
        requestAnimationFrame(resizePlot);
      }
      function chooseTab(tab) {
        state.tab = tab;
        all('[data-awb-tab]').forEach(function (button) { button.setAttribute('aria-selected', String(button.dataset.awbTab === tab)); button.tabIndex = button.dataset.awbTab === tab ? 0 : -1; });
        all('[data-awb-content]').forEach(function (panel) { panel.hidden = panel.dataset.awbContent !== tab; });
      }
      function labelledJson(title, value) {
        return '<details class="awb-json"><summary>' + escape(title) + '</summary><pre>' + escape(JSON.stringify(value, null, 2)) + '</pre></details>';
      }
      function update() {
        const focused = document.activeElement;
        const focusKey = focused && ['awbActive', 'awbVisible', 'awbRemove'].find(function (key) { return Object.prototype.hasOwnProperty.call(focused.dataset, key); });
        const focusValue = focusKey && focused.dataset[focusKey];
        const items = api.items();
        // Only short identities cross to the assistant. Never send curve arrays,
        // file bytes, candidates or client-side scientific claims as evidence.
        window.ArgiloClaySelectionContext = function () {
          return api.items().slice(0,6).map(function (item) {
            const recordId = String(item.record && item.record.id || '');
            return {id:String(item.id || '').slice(0,120), record_id:/^[a-z0-9]{5}-[a-z0-9]{5}$/i.test(recordId) ? recordId : '',
              sample_code:String(item.sampleCode || '').slice(0,120), preparation:String(item.treatment || '').slice(0,120), temporary:Boolean(item.temporaryFile)};
          });
        };
        if (!items.some(function (item) { return item.id === state.activeId; })) state.activeId = items.length ? items[0].id : null;
        if (!items.length && previouslyHadItems) state.mobile = 'samples';
        if (items.length && !previouslyHadItems && !state.activeId) state.mobile = 'chart';
        previouslyHadItems = items.length > 0;
        query('[data-awb-count]').textContent = String(items.length);
        query('[data-awb-samples]').innerHTML = items.map(function (item, index) {
          const metadata = item.metadata || {};
          const filename = metadata.original_filename || metadata.filename || item.id;
          const source = item.temporaryFile ? window.argiloT('Arquivo temporário') : window.argiloT('Do acervo');
          return '<div class="awb-sample' + (state.activeId === item.id ? ' awb-sample--active' : '') + '">' +
            '<input type="checkbox" data-awb-visible="' + escape(item.id) + '"' + (item.workbenchHidden ? '' : ' checked') + ' aria-label="' + escape(window.argiloT('Mostrar curva de {0}', [api.label(item)])) + '">' +
            '<button type="button" class="awb-sample-select" data-awb-active="' + escape(item.id) + '" aria-pressed="' + (state.activeId === item.id) + '"><strong>' + escape(api.label(item)) + '</strong><small><svg viewBox="0 0 24 8" aria-hidden="true"><path d="M1 4h22" stroke="' + escape(api.color(item)) + '" stroke-width="2" stroke-dasharray="' + (index % 3 === 1 ? '5 3' : index % 3 === 2 ? '2 2' : '') + '"></path></svg>' + escape(api.treatment(item.treatment)) + '</small><small>' + escape(source) + '</small><small>' + escape(filename) + '</small></button>' +
            '<button type="button" class="awb-remove" data-awb-remove="' + escape(item.id) + '" aria-label="' + escape(window.argiloT('Remover {0}', [api.label(item)])) + '"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15"></path></svg></button></div>';
        }).join('') || '<p class="awb-small">' + escape(window.argiloT('Selecione arquivos nas Análises para iniciar a comparação.')) + '</p>';
        const active = items.find(function (item) { return item.id === state.activeId; });
        const evidence = query('[data-awb-evidence]');
        if (!active) {
          relationKey = null;
          if (relationRequest) relationRequest.abort();
          evidence.innerHTML = '<div class="awb-evidence-section"><h2>' + escape(window.argiloT('Evidências')) + '</h2><p>' + escape(window.argiloT('Selecione uma amostra para inspecionar os dados.')) + '</p></div>';
          ['peaks', 'provenance', 'records', 'quality', 'results', 'reports'].forEach(function (key) { query('[data-awb-content="' + key + '"]').textContent = window.argiloT('Selecione uma amostra para inspecionar os dados.'); });
        } else {
          const m = active.metadata || {};
          if (state.tab === 'records') relatedRecords(active);
          const candidates = (active.argilominerais || m.argilominerais || []).slice(0, 5);
          const flags = active.qcFlags || m.qc_flags || [];
          const recordId = active.record && active.record.id;
          const recordUrl = recordId && /^[a-z0-9]{5}-[a-z0-9]{5}$/i.test(recordId) ? '/records/' + encodeURIComponent(recordId) : '';
          const originLabel = active.temporaryFile ? window.argiloT('Arquivo temporário') : active.id.startsWith('snapshot:') ? window.argiloT('snapshot geral do módulo DRX') : recordUrl ? window.argiloT('Pacote analítico') : window.argiloT('Não informado');
          const rawUrl = active.id.startsWith('linked:') ? '/scientific/drx/raws/' + encodeURIComponent(active.id.slice(7)) + '/download' : active.id.startsWith('snapshot:') ? '/argiloteca/drx/raw-snapshot/' + encodeURIComponent(active.id) + '/download' : '';
          const fileLink = rawUrl ? '<a class="awb-download" href="' + rawUrl + '" download>' + escape(m.original_filename || m.filename || active.id) + '</a>' : '<p>' + escape(m.original_filename || m.filename || active.id) + '</p>';
          evidence.innerHTML = '<div class="awb-evidence-section"><h2>' + escape(window.argiloT('Evidências')) + '</h2><p class="awb-small">' + escape(window.argiloT('Amostra em inspeção')) + '</p><h3>' + escape(api.label(active)) + '</h3>' + fileLink + '<span class="awb-preparation">' + escape(api.treatment(active.treatment)) + '</span><dl class="awb-definition"><dt>' + escape(window.argiloT('Origem')) + '</dt><dd>' + escape(originLabel) + '</dd><dt>' + escape(window.argiloT('Pontos')) + '</dt><dd>' + escape(number(active.twoTheta.length, 0)) + '</dd><dt>' + escape(window.argiloT('Registro')) + '</dt><dd>' + (recordUrl ? '<a href="' + recordUrl + '">' + escape(recordId) + '</a>' : escape(window.argiloT('Sem vínculo com registro'))) + '</dd></dl></div><div class="awb-evidence-section"><h3>' + escape(window.argiloT('Minerais candidatos')) + '</h3><p class="awb-small">' + escape(window.argiloT('Candidatos do processamento. Não constituem identificação confirmada.')) + '</p><ul class="awb-candidates">' + candidates.map(function (name) { return '<li>' + api.mineralLink(name) + '</li>'; }).join('') + '</ul><a href="/catalogo-autorizado-de-nomes-para-argilominerais">' + escape(window.argiloT('Consultar o Catálogo de Argilominerais')) + '</a></div><div class="awb-evidence-section"><h3>' + escape(window.argiloT('Limitações da análise')) + '</h3><p class="awb-notice">' + escape(window.argiloT('Consulte Qualidade e as evidências completas antes de interpretar os resultados.')) + '</p><button type="button" class="awb-text-button" data-awb-open-quality>' + icon('check') + '<span>' + escape(window.argiloT('Ver qualidade dos dados')) + '</span></button></div>';
          // Measured-curve similarity and curatorial links are distinct evidence.
          const relationText = function (pt, en) { return document.documentElement.lang.startsWith('pt') ? pt : en; };
          const matches = (active.packageSimilarity && active.packageSimilarity.matches) || [];
          const associated = Array.isArray(m.record_links) ? m.record_links : [];
          const related = associated.map(function (link) {
            return '<li><a href="/records/' + encodeURIComponent(link.record_id) + '">' + escape(link.title || link.record_id) + '</a><small> · ' + escape(link.state === 'confirmed' ? relationText('Vínculo confirmado', 'Confirmed link') : relationText('Vínculo pendente de revisão', 'Link awaiting review')) + '</small></li>';
          }).join('');
          const measured = matches.map(function (match) {
            const relatedRecords = (match.record_links || []).map(function (link) {
              return '<a href="/records/' + encodeURIComponent(link.record_id) + '">' + escape(link.record_id) + '</a> (' + escape(link.state === 'confirmed' ? relationText('confirmado', 'confirmed') : relationText('pendente', 'pending')) + ')';
            }).join(', ');
            const score = Number.isFinite(match.curve_score) ? number(match.curve_score, 3) : relationText('não calculado', 'not calculated');
            return '<li><strong>' + escape(match.filename || match.sample_code) + '</strong><p>' + escape(match.exact ? relationText('Mesmo conteúdo (SHA-256)', 'Identical content (SHA-256)') : relationText('Similaridade de curva', 'Curve similarity')) + ' · ' + score + '</p>' + (relatedRecords ? '<p>' + relatedRecords + '</p>' : '') + (match.diffractogram_id ? '<button class="ui button" type="button" data-awb-add-match="' + escape(match.diffractogram_id) + '"' + (items.some(function (item) { return !item.temporaryFile && (item.id === match.diffractogram_id || (match.raw_id && item.metadata && item.metadata.raw_id === match.raw_id)); }) ? ' disabled' : '') + '>' + escape(relationText('Adicionar à comparação', 'Add to comparison')) + '</button>' : '') + '</li>';
          }).join('');
          evidence.insertAdjacentHTML('beforeend', '<section class="awb-evidence-section awb-record-links"><h3>' + escape(relationText('RAWs e registros relacionados', 'Related RAWs and records')) + '</h3>' + (related ? '<ul>' + related + '</ul>' : '<p>' + escape(relationText('Sem vínculo confirmado com registro.', 'No confirmed record link.')) + '</p>') + (measured ? '<p>' + escape(relationText('Curvas medidas da Argiloteca. Similaridade não confirma identificação ou origem; escores não são probabilidades.', 'Measured Argiloteca curves. Similarity does not confirm identification or provenance; scores are not probabilities.')) + '</p><ul>' + measured + '</ul>' : '') + '</section>');
          const peaks = (active.advancedPeaks || []).length ? active.advancedPeaks : (active.detectedPeaks || m.advanced_peaks || []);
          query('[data-awb-content="peaks"]').innerHTML = '<h3>' + escape(api.label(active)) + '</h3>' + table(['2θ (°)', 'd (Å)', window.argiloT('Intensidade'), window.argiloT('Método')], peaks.map(function (peak) { return [number(peak.two_theta), number(peak.d_angstrom || peak.d), number(peak.intensity_relative == null ? peak.intensity : peak.intensity_relative), peak.source || peak.status || window.argiloT('Não informado')]; })) + labelledJson(window.argiloT('Todos os picos e evidências de detecção'), { detected_peaks: active.detectedPeaks, advanced_peaks: active.advancedPeaks, targeted_basal_peaks: active.targetedBasalPeaks });
          query('[data-awb-content="provenance"]').innerHTML = '<h3>' + escape(api.label(active)) + '</h3><dl class="awb-definition"><dt>SHA-256</dt><dd>' + escape(m.source_sha256 || window.argiloT('Não informado')) + '</dd><dt>' + escape(window.argiloT('Alinhamento do eixo')) + '</dt><dd>' + escape(m.two_theta_alignment_method || window.argiloT('Não informado')) + '</dd><dt>' + escape(window.argiloT('Deslocamento 2θ')) + '</dt><dd>' + escape(number(m.two_theta_offset_applied, 6)) + '°</dd></dl>' + labelledJson(window.argiloT('Metadados completos e proveniência'), { metadata: m, traceability: active.traceability, record: active.record, sample: active.sample, analyses: active.analyses, temporary_file: active.temporaryFile ? { name: active.temporaryFile.name, size: active.temporaryFile.size, lastModified: active.temporaryFile.lastModified } : null });
          query('[data-awb-content="quality"]').innerHTML = '<h3>' + escape(api.label(active)) + '</h3><ul class="awb-quality">' + flags.map(function (flag) { return '<li><strong>' + escape(flag.code || flag) + '</strong><p>' + escape(flag.message || '') + '</p></li>'; }).join('') + '</ul>' + labelledJson(window.argiloT('Qualidade e processamento completos'), { qc_flags: flags, advanced_summary: active.advancedSummary, warnings: m.warnings });
          const fits = active.fitResults || m.fit_results || [];
          query('[data-awb-content="results"]').innerHTML = '<h3>' + escape(api.label(active)) + '</h3>' + table(['2θ (°)', 'FWHM (°)', window.argiloT('Situação'), window.argiloT('Método')], fits.map(function (fit) { return [number(fit.center_2theta), number(fit.fwhm), fit.fit_success ? fit.fit_quality || window.argiloT('Não informado') : window.argiloT('Ajuste não convergiu; medida direta'), fit.fwhm_source || fit.fit_message || window.argiloT('Não informado')]; })) + '<p class="awb-small">' + escape(window.argiloT('Valores do processamento existente. FWHM não equivale à quantificação mineralógica.')) + '</p>' + labelledJson(window.argiloT('Resultados completos'), { fit_results: fits, advanced_curve: active.advancedCurve, mineral_evidence: active.mineralEvidence, mineral_characterization: active.mineralCharacterization, reference_comparison: active.referenceComparison });
          query('[data-awb-content="results"]').insertAdjacentHTML('afterbegin', referencePilot(m.reference_pilot));
          if (m.reference_pilot && m.reference_pilot.status !== 'disabled') {
            evidence.insertAdjacentHTML('beforeend', '<div class="awb-evidence-section"><h3>' + escape(window.argiloT('Referências AMCSD e COD · piloto')) + '</h3><p class="awb-small">' + escape(window.argiloT('Compare as reflexões calculadas em Dados → Resultados. A classificação existente foi mantida.')) + '</p><button type="button" class="awb-text-button" data-awb-open-pilot>' + escape(window.argiloT('Ver comparação com referências')) + '</button></div>');
          }
          const report = api.reportUrl(active.id);
          query('[data-awb-content="reports"]').innerHTML = '<h3>' + escape(api.label(active)) + '</h3><p>' + escape(window.argiloT('Os relatórios incluem a seleção completa, mesmo quando uma curva está oculta no gráfico.')) + '</p><div class="awb-report-actions">' + (report ? '<a class="ui button" href="' + escape(report) + '" target="_blank" rel="noopener">' + icon('document') + '<span>' + escape(window.argiloT('Relatório técnico')) + '</span></a>' : '') + '<button type="button" class="ui button" data-awb-export="export-csv">' + icon('download') + '<span>' + escape(window.argiloT('Exportar CSV')) + '</span></button><button type="button" class="ui button" data-awb-export="export-json">' + icon('download') + '<span>' + escape(window.argiloT('Exportar JSON')) + '</span></button><button type="button" class="ui primary button" data-awb-export="export-pdf">' + icon('document') + '<span>' + escape(window.argiloT('Exportar PDF')) + '</span></button></div>' + (active.technicalReport ? labelledJson(window.argiloT('Relatório técnico da sessão'), active.technicalReport) : '');
        }
        const axisNote = query('[data-awb-axis-note]');
        if (axisNote) {
          const warning = api.axisWarning(items);
          axisNote.textContent = warning;
          axisNote.hidden = !warning;
        }
        chooseMobile(state.mobile);
        chooseTab(state.tab);
        grid.classList.toggle('awb-no-evidence', !state.evidence);
        query('[data-awb-toggle-evidence]').setAttribute('aria-expanded', String(state.evidence));
        query('#awb-inspector-content').hidden = !state.inspector;
        query('[data-awb-collapse]').setAttribute('aria-expanded', String(state.inspector));
        (query('[data-awb-collapse] [data-button-label]') || query('[data-awb-collapse]')).textContent = state.inspector ? window.argiloT('Recolher') : window.argiloT('Mostrar');
        if (focusKey && !focused.isConnected) {
          const restored = all('[data-' + focusKey.replace(/[A-Z]/g, function (c) { return '-' + c.toLowerCase(); }) + ']').find(function (element) { return element.dataset[focusKey] === focusValue; });
          if (restored) restored.focus({ preventScroll: true });
        }
      }
      root.addEventListener('click', function (event) {
        const button = event.target.closest('button');
        if (!button) return;
        if (button.dataset.awbMobile) { chooseMobile(button.dataset.awbMobile); persist(); }
        if (button.dataset.awbTab) { if (button.dataset.awbTab === 'records') relationKey = null; chooseTab(button.dataset.awbTab); update(); persist(); }
        if (button.hasAttribute('data-awb-records-retry')) { relationKey = null; update(); }
        if (button.dataset.awbActive) { state.activeId = button.dataset.awbActive; update(); persist(); }
        if (button.dataset.awbAddMatch) { button.disabled = true; button.setAttribute('aria-busy', 'true'); Promise.resolve(api.add(button.dataset.awbAddMatch)).finally(function () { button.removeAttribute('aria-busy'); update(); }); }
        if (button.dataset.awbRemove) { api.remove(button.dataset.awbRemove); }
        if (button.hasAttribute('data-awb-open-pilot')) { state.inspector = true; chooseMobile('inspector'); chooseTab('results'); update(); query('#awb-inspector').scrollIntoView({ block: 'nearest' }); persist(); }
        if (button.hasAttribute('data-awb-toggle-evidence')) { state.evidence = !state.evidence; update(); persist(); }
        if (button.hasAttribute('data-awb-collapse')) { state.inspector = !state.inspector; update(); persist(); }
        if (button.hasAttribute('data-awb-open-quality')) { state.inspector = true; chooseTab('quality'); chooseMobile('inspector'); update(); query('#awb-inspector').scrollIntoView({ block: 'nearest' }); persist(); }
        if (button.dataset.awbExport) query('[data-role="' + button.dataset.awbExport + '"]').click();
      });
      root.addEventListener('change', function (event) {
        const input = event.target;
        if (input.dataset.awbVisible) api.visible(input.dataset.awbVisible, input.checked);
      });
      all('[role="tablist"]').forEach(function (nav) {
        nav.addEventListener('keydown', function (event) {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          const buttons = Array.from(nav.querySelectorAll('[role="tab"]'));
          const index = buttons.indexOf(document.activeElement);
          if (index < 0) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
          buttons[next].focus(); buttons[next].click();
        });
      });
      if (window.ResizeObserver) new ResizeObserver(resizePlot).observe(query('.awb-chart'));
      return {
        update: update,
        focus: function (id) { state.activeId = id; update(); persist(); },
        state: function () { return Object.assign({}, state); },
        restore: function (saved) {
          if (!saved || typeof saved !== 'object') return;
          state.activeId = typeof saved.activeId === 'string' ? saved.activeId : null;
          if (['peaks', 'provenance', 'records', 'quality', 'ngc', 'results', 'reports'].includes(saved.tab)) state.tab = saved.tab;
          if (['samples', 'chart', 'evidence', 'inspector'].includes(saved.mobile)) state.mobile = saved.mobile;
          state.evidence = saved.evidence !== false;
          state.inspector = saved.inspector !== false;
        }
      };
    }
  };
})();
