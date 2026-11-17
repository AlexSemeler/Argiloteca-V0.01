/* Filter the already visible tool directory; never submit a scientific query. */
(() => {
  const input=document.querySelector('[data-au-query]');
  if (!input) return;
  const form=document.querySelector('[data-au-search-form]');
  const rows=Array.from(document.querySelectorAll('[data-au-tool]'));
  const groups=Array.from(document.querySelectorAll('[data-au-group]'));
  const empty=document.querySelector('[data-au-empty]');
  const status=document.querySelector('[data-au-search-status]');
  const portuguese=document.documentElement.lang.toLowerCase().startsWith('pt');
  const fold=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase().trim();
  const filter=()=>{
    const query=fold(input.value);let found=0;
    for(const row of rows){row.hidden=!fold(row.dataset.auSearch||row.textContent).includes(query);if(!row.hidden)found++;}
    for(const group of groups)group.hidden=!Array.from(group.querySelectorAll('[data-au-tool]')).some(row=>!row.hidden);
    if(empty)empty.hidden=found>0;
    if(status){status.hidden=!query;status.textContent=portuguese?`${found} ferramentas encontradas.`:`${found} tools found.`;}
  };
  input.addEventListener('input',filter);
  form?.addEventListener('submit',event=>{event.preventDefault();filter();});
})();
