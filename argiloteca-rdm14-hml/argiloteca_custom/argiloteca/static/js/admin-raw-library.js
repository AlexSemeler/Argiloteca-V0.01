/* Separate administrative state: never touches the public comparison session. */
(() => {
  'use strict';
  const form = document.querySelector('[data-raw-upload]');
  if (form) {
    const pt = form.dataset.language === 'pt';
    const status = form.querySelector('[role="status"]');
    const button = form.querySelector('button[type="submit"]');
    const errors = {
      complete_confirmed_trio_required: pt ? 'Envie N, G e C e confirme os preparos da mesma amostra.' : 'Submit N, G and C and confirm the same-sample preparations.',
      duplicate_profiles: pt ? 'Dois arquivos contêm o mesmo perfil numérico. Confira os três preparos.' : 'Two files contain the same numerical profile. Check all three preparations.',
      declared_wavelength_required: pt ? 'O comprimento de onda precisa estar declarado no RAW.' : 'The RAW must declare its wavelength.',
      curve_range_requires_review: pt ? 'A faixa ou quantidade de pontos exige revisão antes deste envio.' : 'The scan range or point count requires review before submission.',
      invalid_raw_or_size: pt ? 'Use arquivos RAW de até 8 MiB, um por preparo.' : 'Use RAW files up to 8 MiB, one per preparation.'
    };
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!form.reportValidity() || form.getAttribute('aria-busy') === 'true') return;
      form.setAttribute('aria-busy', 'true'); button.disabled = true;
      status.removeAttribute('data-error');
      status.textContent = pt ? 'Validando, anonimizando e classificando o trio. Aguarde…' : 'Validating, anonymizing and classifying the trio. Please wait…';
      try {
        const response = await fetch(form.action, {method:'POST', body:new FormData(form), headers:{Accept:'application/json'}, credentials:'same-origin'});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(errors[data.error] || (pt ? 'Não foi possível concluir. Confira o formato dos RAWs e sua sessão antes de tentar novamente.' : 'Could not complete submission. Check RAW formats and your session before retrying.'));
        status.textContent = pt ? 'Trio restrito salvo. Abrindo os resultados…' : 'Restricted trio saved. Opening results…';
        window.location.assign(data.location);
      } catch (error) {
        status.setAttribute('data-error', 'true'); status.textContent = error.message;
        button.disabled = false; form.removeAttribute('aria-busy');
      }
    });
  }
  const chart = document.querySelector('[data-raw-curve]');
  if (chart) {
    const pt = chart.dataset.language === 'pt';
    const status = document.querySelector('.rl-chart-status');
    fetch(chart.dataset.rawCurve, {credentials:'same-origin', headers:{Accept:'application/json'}})
      .then(response => { if (!response.ok) throw new Error('curve'); return response.json(); })
      .then(data => {
        if (!window.Plotly) throw new Error('plot');
        const axis = data.axis_kind === 'two_theta_degrees' ? '2θ (°)' : pt ? 'Coordenada nativa — unidade não confirmada' : 'Native coordinate — unit unconfirmed';
        return Plotly.newPlot(chart, [{x:data.x,y:data.intensity,type:'scatter',mode:'lines',name:data.filename,line:{color:'#704025',width:1.5}}],
          {margin:{l:55,r:15,t:20,b:65},xaxis:{title:axis},yaxis:{title:pt?'Intensidade':'Intensity'},paper_bgcolor:'#f4f1eb',plot_bgcolor:'#fff',font:{family:'Lato, sans-serif',color:'#34291f'},showlegend:false},
          {responsive:true,displaylogo:false,scrollZoom:false}).then(() => { status.textContent = pt ? `${data.original_points} pontos originais · curva anônima, sem alteração do eixo.` : `${data.original_points} original points · anonymous curve, unchanged axis.`; });
      }).catch(() => { status.textContent = pt ? 'Não foi possível carregar a curva. Recarregue a página ou consulte as pendências.' : 'The curve could not be loaded. Reload the page or review the outstanding issues.'; });
  }
})();

// Native POST remains functional without JavaScript; prevent accidental double submissions.
(() => {
  const form = document.querySelector('.rl-curation-form');
  if (!form) return;
  const license = form.querySelector('[name=license]');
  const rights = form.querySelector('[name=confirm_rights]');
  const updateRights = () => { rights.required = !!license.value; };
  license.addEventListener('change', updateRights); updateRights();
  form.addEventListener('submit', event => {
    if (form.getAttribute('aria-busy') === 'true') { event.preventDefault(); return; }
    if (!form.checkValidity()) return;
    form.setAttribute('aria-busy', 'true');
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = document.documentElement.lang.startsWith('pt') ? 'Preparando rascunho…' : 'Preparing draft…';
  });
})();

(() => {
  const chart = document.querySelector('[data-ngc-chart]');
  if (!chart) return;
  const status = document.querySelector('.ngc-chart-status');
  const pt = chart.dataset.language === 'pt';
  fetch(chart.dataset.ngcChart, {credentials:'same-origin',headers:{Accept:'application/json'}})
    .then(response => {if (!response.ok) throw new Error('joint_analysis'); return response.json();})
    .then(report => {
      if (!window.Plotly || report.curves?.length !== 3) throw new Error('curves');
      const colors=['#704025','#326d70','#a65b35'];
      const dashes=['solid','dash','dot'];
      const traces=report.curves.map((c,i)=>{
        const maximum=Math.max(...c.intensity.map(Math.abs));
        return {x:c.x,y:c.intensity.map(v=>maximum>0?v/maximum:v),type:'scatter',mode:'lines',
          name:c.preparation+' · λ '+c.wavelength_angstrom+' Å',line:{color:colors[i],dash:dashes[i],width:1.5}};
      });
      return Plotly.newPlot(chart,traces,{margin:{l:55,r:15,t:35,b:65},xaxis:{title:'2θ (°)'},
        yaxis:{title:pt?'Intensidade / máximo absoluto':'Intensity / absolute maximum'},
        legend:{orientation:'h',y:1.15},paper_bgcolor:'#f4f1eb',plot_bgcolor:'#fff',
        font:{family:'Lato, sans-serif',color:'#34291f'}},{responsive:true,displaylogo:false,scrollZoom:false})
        .then(()=>{status.textContent=pt?'Três curvas carregadas. Dados e resultados salvos preservados.':'Three curves loaded. Saved data and results preserved.';});
    }).catch(()=>{status.textContent=pt?'Não foi possível carregar a comparação. Os resultados textuais salvos continuam disponíveis; recarregue a página para tentar novamente.':'Could not load the comparison. Saved text results remain available; reload the page to retry.';});
})();
