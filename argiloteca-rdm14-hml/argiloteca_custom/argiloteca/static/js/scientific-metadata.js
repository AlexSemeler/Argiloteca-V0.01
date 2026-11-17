/* Structured scientific authoring. Native record services own validation and persistence. */
(function () {
  'use strict';
  const config = JSON.parse(document.getElementById('science-config').textContent);
  const pt = config.language === 'pt';
  const t = (en, br) => pt ? br : en;
  const state = structuredClone(config.record);
  let changeVersion = 0, savedVersion = 0, saving = false;
  const dirty = () => { changeVersion += 1; };
  window.addEventListener('beforeunload', event => { if (!config.read_only && changeVersion !== savedVersion) { event.preventDefault(); event.returnValue = ''; } });
  const sectionId = field => 'science-section-' + field.replace(':','-');
  const sectionNotes = {
    'arg:pesquisas_campo': ['A campaign ID links fieldwork to the samples collected.', 'O ID da campanha relaciona a pesquisa de campo às amostras coletadas.'],
    'arg:amostras': ['Use the campaign ID to connect a sample to its fieldwork. Its sample ID is used by analyses and results.', 'Use o ID da campanha para vincular a amostra à pesquisa de campo. O código da amostra é usado nas análises e nos resultados.'],
    'arg:analises': ['Connect each analysis to a sample by its sample ID. Use the analysis ID in chemical results and analytical packages.', 'Relacione cada análise à amostra pelo código da amostra. Use o ID da análise nos resultados químicos e nos pacotes analíticos.'],
    'arg:composicao_quimica_global': ['Identify the sample and analysis associated with these chemical results.', 'Identifique a amostra e a análise associadas a estes resultados químicos.'],
    'arg:argilominerais': ['Connect identified clay minerals to the corresponding sample.', 'Relacione os argilominerais identificados à amostra correspondente.'],
    'arg:pacotes_analiticos': ['Group analytical results while preserving their sample and analysis identifiers.', 'Agrupe os resultados analíticos mantendo os identificadores de amostra e análise.'],
    'arg:publicacoes_relacionadas': ['Add publications associated with the scientific context of this record.', 'Inclua publicações associadas ao contexto científico deste registro.'],
    'arg:referencias_drx_webmineral': ['Reference data supports comparison; it does not establish identification on its own.', 'Dados de referência apoiam a comparação; não comprovam uma identificação isoladamente.']
  };
  const referenceFields = {
    campanha_id: ['arg:pesquisas_campo','campanha_id'],
    codigo_amostra: ['arg:amostras','codigo_amostra'],
    analise_id: ['arg:analises','analise_id']
  };
  function referenceHelp(row, input, key, path) {
    const target = referenceFields[key];
    if (!target || path[1] === target[0] || input.tagName !== 'INPUT') return;
    const id = input.id + '-choices';
    const values = (state.custom_fields[target[0]] || []).map(item => item[target[1]]).filter(value => value !== undefined && value !== null && value !== '');
    if (values.length) { const list = el('datalist',{id}); for (const value of [...new Set(values)]) list.append(el('option',{value})); input.setAttribute('list', id); row.append(list); }
    const help = el('p',{class:'science-field-help',id:input.id+'-help'});
    help.append(document.createTextNode(t('Related section: ','Seção relacionada: ')));
    const link = el('a',{href:'#'+sectionId(target[0])},label(target[0]));help.append(link);row.append(help);input.setAttribute('aria-describedby',help.id);
  }
  document.querySelectorAll('.science-relationships a').forEach(link => link.addEventListener('click', () => { const target=document.getElementById(link.hash.slice(1)); if(target) target.open=true; }));
  const blockNames = {
    'arg:pesquisas_campo': ['Field campaigns','Pesquisas de campo'],
    'arg:amostras': ['Samples','Amostras'], 'arg:analises': ['Analyses','Análises'],
    'arg:composicao_quimica_global': ['Global chemical composition','Composição química global'],
    'arg:argilominerais': ['Clay minerals','Argilominerais'],
    'arg:publicacoes_relacionadas': ['Related publications','Publicações relacionadas'],
    'arg:pacotes_analiticos': ['Analytical packages','Pacotes analíticos'],
    'arg:referencias_drx_webmineral': ['Auxiliary WebMineral references','Referências auxiliares WebMineral']
  };
  const enNames = {person_or_org:'Person or organization',family_name:'Family name',given_name:'Given name',altitude:'Altitude',raw_sha256:'RAW SHA-256',two_theta:'2θ',two_theta_min:'Minimum 2θ',two_theta_max:'Maximum 2θ',d_spacing:'d spacing',webmineral_url:'WebMineral URL',a_to_b:'a/b ratio',b_to_b:'b/b ratio',c_to_b:'c/b ratio',hm_symbol:'Hermann–Mauguin symbol',resource_type:'Resource type',
    codigo_amostra:'Sample ID',campanha_id:'Campaign ID',titulo:'Title',data_coleta:'Collection date',responsavel_coleta:'Collected by',local_coleta:'Collection location',descricao_local:'Location description',altitude_m:'Altitude (m)',coordenada:'Coordinates',localidade:'Locality',deposito:'Deposit',contexto_geologico:'Geological context',tempo_geologico:'Geological time',rocha_hospedeira:'Host rock',tipo_amostra:'Sample type',observacoes_campo:'Field observations',analise_id:'Analysis ID',metodo:'Method',metodo_analitico:'Analytical method',data_analise:'Analysis date',laboratorio:'Laboratory',equipamento:'Equipment',condicoes_analise:'Analysis conditions',resultado_principal:'Main result',interpretacao:'Interpretation',arquivo_resultado:'Result file',checksum_resultado:'Result checksum',observacoes:'Notes',nome:'Name',nome_cientifico_padronizado:'Standard scientific name',sinonimos:'Synonyms',formula_ideal:'Ideal formula',grupo:'Group',grupo_mineralogico:'Mineralogical group',subgrupo_mineralogico:'Mineralogical subgroup',descricao:'Description',descricao_curta:'Short description',estrutura_cristalina:'Crystal structure',classe_estrutural:'Structural class',sistema_cristalino:'Crystal system',classificacao_strunz:'Strunz classification',classificacao_dana:'Dana classification',propriedades_especiais:'Special properties',propriedades_relevantes:'Relevant properties',origem_formacao:'Formation origin',ambiente_tipico_formacao:'Typical formation environment',era_geologica:'Geological era',formacao_geologica:'Geological formation',usos_aplicacoes:'Uses and applications',fonte_descricao:'Description source',observacao_proveniencia:'Provenance notes',licenca_fonte:'Source license',data_ultima_sincronizacao:'Last synchronization date',precisao_m:'Precision (m)',fonte:'Source',metodo_obtencao:'Acquisition method',deposito_id:'Deposit ID',tipo:'Type',substancia:'Substance',titular:'Holder',fase_processo:'Process stage',processo_anm:'ANM process',area_ha:'Area (ha)',url_fonte:'Source URL',arquivo_raw:'RAW file',tamanho_bytes:'Size (bytes)',formato_raw:'RAW format',preparo:'Preparation',processamento_id:'Processing ID',versao_processamento:'Processing version',data_processamento:'Processing date',numero_pontos:'Number of points',picos:'Peaks',intensidade:'Intensity',prominencia:'Prominence',minerais_candidatos:'Candidate minerals',confianca:'Confidence',evidencia:'Evidence',relatorio_html:'HTML report',relatorio_pdf:'PDF report',componente_dominante:'Dominant component',enriquecimento_relativo:'Relative enrichment',predominancia_mineral:'Mineral predominance',classe_geoquimica:'Geochemical class',pais:'Country',uf:'State',municipio:'Municipality',bacia:'Basin',metodo_id:'Method ID',pacote_id:'Package ID',data_inicio:'Start date',data_fim:'End date',responsavel:'Responsible person',equipe:'Team',area_estudo:'Study area',objetivo:'Objective',autores:'Authors',ano:'Year',fonte_ou_revista:'Source or journal',identificador_externo:'External identifier',codigo_analise:'Analysis ID',argilomineral_nome:'Clay mineral name',relacao_com_registro:'Relation to record',papel_da_amostra:'Sample role',argilomineral_id:'Clay mineral ID',fonte_metodo:'Method source'
  };
  const brNames = {altitude:'Altitude',raw_sha256:'SHA-256 do RAW',two_theta:'2θ',two_theta_min:'2θ mínimo',two_theta_max:'2θ máximo',d_spacing:'Espaçamento d',webmineral_url:'URL do WebMineral',a_to_b:'Relação a/b',b_to_b:'Relação b/b',c_to_b:'Relação c/b',hm_symbol:'Símbolo Hermann–Mauguin',score:'Pontuação',resource_type:'Tipo de recurso',family_name:"Sobrenome",given_name:"Nome",person_or_org:"Pessoa ou organização",name:"Nome",type:"Tipo",analysis_type:'Tipo de análise',generated_at:'Gerado em',record_id:'ID do registro',source:'Fonte',summary:'Resumo',items:'Itens',manifest_path:'Caminho do manifesto',source_url:'URL da fonte',source_file:'Arquivo de origem',source_snapshot:'Cópia da fonte',validation_status:'Estado de validação',reference_kind:'Tipo de referência',usage:'Uso',has_drx_reference:'Possui referência DRX',lines:'Linhas',lines_count:'Número de linhas',relative_intensity:'Intensidade relativa',d_angstrom:'d (Å)',chemical_formula:'Fórmula química',empirical_formula:'Fórmula empírica',chemical_composition:'Composição química',has_chemical_composition:'Possui composição química',elements:'Elementos',oxides:'Óxidos',element:'Elemento',symbol:'Símbolo',weight_percent:'Percentual em massa',oxide:'Óxido',source_element:'Elemento de origem',molecular_weight_g_mol:'Massa molar (g/mol)',total_oxide_percent:'Total de óxidos (%)',elements_count:'Número de elementos',oxides_count:'Número de óxidos',composition_entries:'Entradas de composição',has_crystallography:'Possui cristalografia',has_structural_classification:'Possui classificação estrutural',has_structure_reference:'Possui referência estrutural',has_auxiliary_qc:'Possui controle auxiliar de qualidade',cell_parameters:'Parâmetros de cela',has_cell_parameters:'Possui parâmetros de cela',axial_ratios:'Relações axiais',crystal_system:'Sistema cristalino',space_group:'Grupo espacial',xray_summary:'Resumo de raios X',raw:'Original',source_status:'Estado da fonte',title_pt:'Título em português',category:'Categoria',family:'Família',vocabulary_source:'Vocabulário de origem',local_html:'HTML local',classifier_feature_groups:'Grupos de atributos do classificador',classifier_feature_count:'Número de atributos do classificador',errors:'Erros',density:'Densidade',electron_density:'Densidade eletrônica',photoelectric:'Fotoelétrico',radioactivity:'Radioatividade',structure_reference:'Referência estrutural',jpowd_model:'Modelo JPOWD',webmineral_crystallography:'Cristalografia WebMineral',webmineral_classification:'Classificação WebMineral',webmineral_structure_reference:'Referência estrutural WebMineral',webmineral_auxiliary_qc:'Controle auxiliar WebMineral',webmineral_descriptive_properties:'Propriedades descritivas WebMineral',provenance:'Proveniência',external_id:'ID externo',external_source:'Fonte externa',external_uri:'URI externa',title:'Título',publication_date:'Data de publicação',publisher:'Editora',description:'Descrição',creators:'Autores',identifiers:'Identificadores',calculated_density_g_cm3:'Densidade calculada (g/cm³)',a_angstrom:'a (Å)',b_angstrom:'b (Å)',c_angstrom:'c (Å)',volume_angstrom3:'Volume (Å³)',alpha_deg:'α (graus)',beta_deg:'β (graus)',gamma_deg:'γ (graus)'};
  Object.assign(brNames,{codigo_amostra:'Código da amostra',campanha_id:'ID da campanha',analise_id:'ID da análise',altitude_m:'Altitude (m)',data_coleta:'Data de coleta',local_coleta:'Local de coleta',descricao_local:'Descrição do local',contexto_geologico:'Contexto geológico',observacoes_campo:'Observações de campo',responsavel_coleta:'Responsável pela coleta',tipo_amostra:'Tipo de amostra'});
  const accents={analise:'análise',analitico:'analítico',codigo:'código',descricao:'descrição',coordenada:'coordenada',localidade:'localidade',deposito:'depósito',metodo:'método',observacoes:'observações',geologico:'geológico',geologica:'geológica',quimica:'química',classificacao:'classificação',confianca:'confiança',evidencia:'evidência',proveniencia:'proveniência',licenca:'licença',ultima:'última',sincronizacao:'sincronização',precisao:'precisão',obtencao:'obtenção',substancia:'substância',numero:'número',intensidade:'intensidade',prominencia:'proeminência',relatorio:'relatório',aplicacoes:'aplicações',responsavel:'responsável',pais:'país',municipio:'município',inicio:'início',publicacao:'publicação',relacao:'relação',padronizado:'padronizado',cristalina:'cristalina',formacao:'formação',oxido:'óxido',oxidos:'óxidos'};
  function label(key){
    if(blockNames[key])return blockNames[key][pt?1:0];
    if(!pt&&enNames[key])return enNames[key];if(pt&&brNames[key])return brNames[key];
    const text=key.replaceAll('_',' ').split(' ').map(w=>pt?(accents[w]||w):w).join(' ');
    return text[0].toUpperCase()+text.slice(1);
  }
  function el(tag,props={},text){const node=document.createElement(tag);for(const[k,v]of Object.entries(props)){if(k==='class')node.className=v;else node.setAttribute(k,v);}if(text!==undefined)node.textContent=text;return node;}
  function get(path){let v=state;for(const key of path){if(v===undefined||v===null)return undefined;v=v[key];}return v;}
  function set(path,value){dirty();let v=state;for(const key of path.slice(0,-1)){if(v[key]===undefined)v[key]={};v=v[key];}if(value===undefined)delete v[path.at(-1)];else v[path.at(-1)]=value;}
  function resolve(def){return def.$ref?config.schemas[def.$ref]:def;}
  function kind(def){const value=def.type;return Array.isArray(value)?value.find(k=>k!=='null'):value;}
  function initial(def){def=resolve(def);return kind(def)==='array'?[]:kind(def)==='object'?{}:kind(def)==='boolean'?false:'';}
  const variants={};
  function renderField(parent,key,definition,path,required=false){
    const def=resolve(definition),value=get(path),type=kind(def),id='science-'+path.map(encodeURIComponent).join('-');
    const row=el('div',{class:'science-field'}),name=el('label',{for:id},label(key)+(required?' *':''));row.append(name);
    const presence=el('select',{class:'science-presence','aria-label':t('Presence: ','Presença: ')+label(key)});
    for(const[v,text]of[['absent',t('Absent','Ausente')],['value',t('Value','Valor')],...(Array.isArray(def.type)&&def.type.includes('null')?[['null',t('Null','Nulo')]]:[])])presence.append(el('option',{value:v},text));
    presence.value=value===undefined?'absent':value===null?'null':'value';row.append(presence);
    presence.addEventListener('change',()=>{set(path,presence.value==='absent'?undefined:presence.value==='null'?null:initial(def));render();});
    if(value===undefined||value===null){name.htmlFor=id+'-presence';presence.id=id+'-presence';row.append(el('span',{},presence.value==='null'?t('Explicit null value','Valor nulo explícito'):t('Not supplied','Não informado')));parent.append(row);return;}
    if(type==='object'||type==='array'){
      name.htmlFor=id+'-presence';presence.id=id+'-presence';
      row.append(el('span',{},type==='array'?String(value.length)+' '+t('item(s)','item(ns)'):t('Structured block','Bloco estruturado')));parent.append(row);
      const box=el('fieldset',{class:'science-object'});box.append(el('legend',{},label(key)));parent.append(box);
      if(type==='array'){
        if(!Array.isArray(value)){box.append(el('p',{},t('Invalid list: correct the value before publishing.','Lista inválida: corrija o valor antes de publicar.')));return;}
        value.forEach((_,index)=>{const item=el('div',{class:'science-repeat-item'});box.append(item);item.append(el('h4',{},t('Item ','Item ')+(index+1)));
          let entry=def.items||{};
          if(entry.anyOf){const selector=el('select',{'aria-label':t('Item structure','Estrutura do item')});selector.append(el('option',{value:'drx'},t('Structured XRD result','Resultado DRX estruturado')),el('option',{value:'generic'},t('Other object','Outro objeto')));const variantKey=path.concat(index).join('/');const drxDef=resolve(entry.anyOf[0]),itemValue=get(path.concat(index));selector.value=variants[variantKey]||((drxDef.required||[]).every(key=>Object.hasOwn(itemValue||{},key))?'drx':'generic');selector.onchange=()=>{variants[variantKey]=selector.value;render();};item.append(selector);entry=entry.anyOf[selector.value==='drx'?0:1];}
          renderValue(item,entry,path.concat(index));const remove=el('button',{type:'button',class:'ui small basic negative button'},t('Remove item','Remover item'));remove.onclick=()=>{get(path).splice(index,1);dirty();render();};item.append(remove);
        });
        const add=el('button',{type:'button',class:'ui small button'},t('Add item: ','Adicionar item: ')+label(key));add.onclick=()=>{let entry=def.items||{};if(entry.anyOf)entry=entry.anyOf[0];const next=get(path).length;if(def.items?.anyOf)variants[path.concat(next).join('/')] = 'drx';get(path).push(initial(entry));dirty();render();};box.append(add);
      }else renderValue(box,def,path);
      return;
    }
    let input;
    if(def.enum||def.const!==undefined){input=el('select',{id});for(const option of def.enum||[def.const])input.append(el('option',{value:option},key==='id'&&path.at(-2)==='resource_type'?(config.resource_types.find(r=>r.id===option)?.label||option):key==='tipo'&&config.method_labels[option]?config.method_labels[option]:option));input.value=value;input.onchange=()=>set(path,input.value);}
    else if(type==='boolean'){input=el('input',{id,type:'checkbox'});input.checked=value;input.onchange=()=>set(path,input.checked);}
    else{input=el('input',{id,type:type==='number'||type==='integer'?'number':'text',...(type==='number'?{step:'any'}:{})});input.value=value;input.oninput=()=>set(path,type==='number'||type==='integer'?(input.value===''?'':Number(input.value)):input.value);}
    row.append(input);referenceHelp(row,input,key,path);parent.append(row);
  }
  function renderValue(parent,definition,path){
    const def=resolve(definition),value=get(path);
    if(def.properties){
      if(def.anyOf)parent.append(el('p',{},t('Supply at least one alternative: ','Informe ao menos uma alternativa: ')+def.anyOf.map(x=>(x.required||[]).map(label).join(' + ')).join(' / ')));
      for(const[key,sub]of Object.entries(def.properties))renderField(parent,key,sub,path.concat(key),(def.required||[]).includes(key));
      const extra=Object.fromEntries(Object.entries(value||{}).filter(([key])=>!Object.hasOwn(def.properties,key)));
      if(Object.keys(extra).length){const note=el('details');note.append(el('summary',{},t('Existing additional values (preserved)','Valores adicionais existentes (preservados)')),el('pre',{},JSON.stringify(extra,null,2)));parent.append(note);}
    }else if(kind(def)==='object'||!def.type){const textarea=el('textarea',{class:'science-json','aria-label':t('Free-form object (JSON)','Objeto livre (JSON)')});textarea.value=JSON.stringify(value,null,2);textarea.onchange=()=>{try{set(path,JSON.parse(textarea.value));textarea.setCustomValidity('');}catch(error){textarea.setCustomValidity(t('Invalid JSON','JSON inválido'));textarea.reportValidity();}};parent.append(textarea);}
    else renderField(parent,t('Value','Valor'),def,path,true);
  }
  function basicField(parent, key, path, required=false, options=null) {
    const id='science-'+path.map(encodeURIComponent).join('-'),row=el('div',{class:'field'}),name=el('label',{for:id},label(key)+(required?' *':''));
    row.append(name);let input;
    if(options){input=el('select',{id});const current=get(path);if(current&&!options.some(o=>o.id===current))input.append(el('option',{value:current},current));for(const option of options)input.append(el('option',{value:option.id},option.id==='dataset'?t('Dataset','Conjunto de dados'):option.label));input.value=current??'';input.onchange=()=>set(path,input.value);}
    else {input=el(key==='description'?'textarea':'input',{id,...(key==='description'?{rows:'4'}:{type:'text'})});input.value=get(path)??'';input.oninput=()=>set(path,input.value);}
    if(required)input.setAttribute('aria-required','true');row.append(input);parent.append(row);return input;
  }
  function renderBibliography(){
    const bibliography=document.getElementById('science-bibliography');bibliography.replaceChildren(el('h2',{},t('Basic information','Informações básicas')));
    basicField(bibliography,'resource_type',['metadata','resource_type','id'],true,config.resource_types);
    basicField(bibliography,'title',['metadata','title'],true);
    basicField(bibliography,'publication_date',['metadata','publication_date'],true);
    const authors=el('fieldset',{class:'science-authors'});authors.append(el('legend',{},label('creators')+' *'));bibliography.append(authors);
    const creators=state.metadata.creators||[];
    creators.forEach((creator,index)=>{
      const item=el('div',{class:'science-author'});authors.append(item);item.append(el('h3',{},t('Creator ','Autor ')+(index+1)));
      const path=['metadata','creators',index,'person_or_org'];
      const type=basicField(item,'type',path.concat('type'),true,[{id:'personal',label:t('Person','Pessoa')},{id:'organizational',label:t('Organization','Organização')}]);
      type.onchange=()=>{set(path.concat('type'),type.value);render();};
      if(creator.person_or_org?.type==='organizational')basicField(item,'name',path.concat('name'),true);
      else {const names=el('div',{class:'two fields'});item.append(names);basicField(names,'family_name',path.concat('family_name'),true);basicField(names,'given_name',path.concat('given_name'));}
      const remove=el('button',{type:'button',class:'ui basic negative button'},t('Remove creator','Remover autor'));remove.onclick=()=>{creators.splice(index,1);dirty();render();};item.append(remove);
    });
    const add=el('button',{type:'button',class:'ui basic button'},t('Add creator','Adicionar autor'));add.onclick=()=>{if(!state.metadata.creators)state.metadata.creators=[];state.metadata.creators.push({person_or_org:{type:'personal',family_name:'',given_name:''}});dirty();render();};authors.append(add);
    basicField(bibliography,'description',['metadata','description']);basicField(bibliography,'publisher',['metadata','publisher']);
  }
  function render(){
    renderBibliography();
    const blocks=document.getElementById('science-blocks');blocks.replaceChildren();
    for(const[field,[filename,multiple]]of ['arg:pesquisas_campo','arg:amostras','arg:analises','arg:composicao_quimica_global','arg:argilominerais','arg:pacotes_analiticos','arg:publicacoes_relacionadas','arg:referencias_drx_webmineral'].map(field=>[field,config.bindings[field]]).filter(([,binding])=>binding)){const details=el('details',{class:'science-block',id:sectionId(field)});if(get(['custom_fields',field])!==undefined)details.open=true;details.append(el('summary',{},label(field)));if(sectionNotes[field])details.append(el('p',{class:'science-section-note'},sectionNotes[field][pt?1:0]));blocks.append(details);renderField(details,field,multiple?{type:'array',items:{$ref:filename}}:{$ref:filename},['custom_fields',field]);}
    document.getElementById('science-profile').checked=state.custom_fields[config.profile_field]===config.profile_version;
    updateLinks();
    if(config.read_only)for(const node of document.querySelectorAll("#science-form input,#science-form select,#science-form textarea,#science-form button"))node.disabled=true;
  }
  function updateLinks(){document.getElementById('science-record-state').textContent=(state.is_published?t('Published record','Registro publicado'):t('Draft','Rascunho'))+(state.id?' · '+state.id:'');
    for(const link of document.querySelectorAll('.argilo-deposit-tabs a')) { if(link.getAttribute('href').startsWith('/uploads/'))link.href=state.id?'/uploads/'+encodeURIComponent(state.id):'/uploads/new';if(link.getAttribute('href').startsWith('/scientific/deposit'))link.href=state.id?'/scientific/deposit/'+encodeURIComponent(state.id):'/scientific/deposit'; }
    const links=document.getElementById('science-record-links');links.replaceChildren();if(state.id){const native=el('a',{href:'/uploads/'+encodeURIComponent(state.id),class:'ui basic button'},t('Full native deposit form','Formulário nativo completo'));links.append(native);if(state.is_published)links.append(el('a',{href:'/records/'+encodeURIComponent(state.id),class:'ui basic button'},t('View published record','Ver registro publicado')));}}
  function errors(data){
    const node=document.getElementById('science-errors');node.replaceChildren();
    if(!data||(Array.isArray(data)?!data.length:!Object.keys(data).length))return;
    node.append(el('strong',{},t('Please review these fields before publishing:','Revise estes campos antes de publicar:')));
    const list=el('ul');node.append(list);
    const append=(field,message)=>{const item=el('li'),id='science-'+field.split('.').map(encodeURIComponent).join('-'),target=document.getElementById(id),text=field.split('.').filter(k=>!['metadata','custom_fields'].includes(k)).map(k=>/^\d+$/.test(k)?String(Number(k)+1):label(k)).join(' / ');if(target){const link=el('a',{href:'#'+encodeURIComponent(id)},text||t('Field','Campo'));link.onclick=event=>{event.preventDefault();for(let e=target.parentElement;e;e=e.parentElement)if(e.tagName==='DETAILS')e.open=true;target.focus();target.scrollIntoView({block:'center'});};item.append(link,document.createTextNode(': '+message));}else item.textContent=(text?text+': ':'')+message;list.append(item);};
    const walk=(value,path='')=>{if(Array.isArray(value)){for(const entry of value){if(entry&&typeof entry==='object'&&entry.field)walk(entry.messages||entry.message,entry.field);else walk(entry,path);}}else if(value&&typeof value==='object'){for(const[key,entry]of Object.entries(value))walk(entry,path?path+'.'+key:key);}else if(value!==undefined)append(path,String(value));};
    walk(data);
    const details=el('details');details.append(el('summary',{},t('Validation details','Detalhes da validação')),el('pre',{},JSON.stringify(data,null,2)));node.append(details);
  }
  async function send(url,method,body){const response=await fetch(url,{method,headers:{'Content-Type':'application/json','X-CSRFToken':config.csrf_token},body:JSON.stringify(body)});let data;try{data=await response.json();}catch(_){throw Error(t('The session has expired. Reload the page and log in again.','A sessão expirou. Recarregue a página e entre novamente.'));}if(!response.ok){errors(data.errors||[]);throw Error(data.message||t('Operation failed.','A operação falhou.'));}return data;}
  async function save(publish=false){if(saving)return;saving=true;const requestVersion=changeVersion;for(const id of ['science-save','science-publish','science-confirm-publish'])document.getElementById(id).disabled=true;const status=document.getElementById('science-status');status.textContent=t('Saving…','Salvando…');try{
    for(const input of document.querySelectorAll('.science-json'))if(!input.checkValidity())throw Error(t('Correct the JSON fields.','Corrija os campos JSON.'));
    const body={metadata:state.metadata,custom_fields:Object.fromEntries(Object.keys(config.bindings).concat(config.profile_field).filter(k=>Object.hasOwn(state.custom_fields,k)).map(k=>[k,state.custom_fields[k]])),remove_fields:Object.keys(config.bindings).concat(config.profile_field).filter(k=>!Object.hasOwn(state.custom_fields,k)),revision_id:config.revision_id};
    if(!state.id){body.access=state.access;body.files=state.files;}
    let result=await send(state.id?'/scientific/drafts/'+encodeURIComponent(state.id):'/scientific/drafts',state.id?'PUT':'POST',body);
    state.id=result.record.id;savedVersion=requestVersion;config.revision_id=result.revision_id;history.replaceState({},'', '/scientific/deposit/'+encodeURIComponent(state.id));errors(result.errors||[]);updateLinks();
    status.textContent=(result.errors||[]).length?t('Draft saved with validation issues.','Rascunho salvo com pendências de validação.'):t('Draft saved.','Rascunho salvo.');
    if(publish){result=await send('/scientific/drafts/'+encodeURIComponent(state.id)+'/publish','POST',{revision_id:config.revision_id});state.is_published=true;status.textContent=t('Published successfully.','Publicado com sucesso.');errors([]);updateLinks();document.getElementById('science-save').disabled=true;document.getElementById('science-publish').disabled=true;}
  }catch(error){status.textContent=error.message;}finally{saving=false;for(const id of ['science-save','science-publish','science-confirm-publish'])document.getElementById(id).disabled=!!state.is_published;}}
  if(config.read_only){render();const begin=document.getElementById('science-begin-edit');if(begin)begin.onclick=async()=>{try{await send('/scientific/records/'+encodeURIComponent(state.id)+'/edit','POST',{});location.reload();}catch(error){document.getElementById('science-status').textContent=error.message;}};}
  else{document.getElementById('science-profile').onchange=function(){dirty();if(this.checked)state.custom_fields[config.profile_field]=config.profile_version;else delete state.custom_fields[config.profile_field];};document.getElementById('science-save').onclick=()=>save(false);document.getElementById('science-publish').onclick=()=>{document.getElementById('science-publish-confirm').hidden=false;document.getElementById('science-confirm-publish').focus();};document.getElementById('science-cancel-publish').onclick=()=>{document.getElementById('science-publish-confirm').hidden=true;document.getElementById('science-publish').focus();};document.getElementById('science-confirm-publish').onclick=()=>save(true);render();}
}());
