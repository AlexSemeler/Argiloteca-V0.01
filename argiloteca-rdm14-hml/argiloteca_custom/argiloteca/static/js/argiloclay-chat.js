/* Read-only conversation. Retrieved text is rendered literally, never as HTML. */
(function () {
  'use strict';
  const app = document.querySelector('[data-chat-app]');
  if (!app) return;
  const text = JSON.parse(document.getElementById('chat-messages-config').textContent);
  const input = document.getElementById('chat-input');
  const send = app.querySelector('.chat-send');
  const messages = app.querySelector('[data-messages]');
  const history = document.getElementById('chat-history');
  const sources = document.getElementById('chat-sources');
  const toggleSources = app.querySelector('[data-toggle-sources]');
  const status = app.querySelector('[data-chat-status]');
  const note = document.getElementById('chat-prototype-note');
  const narrow = window.matchMedia('(max-width: 899px)');
  const storageKey = 'argiloclay-connected-session-v2-' + text.accountScope;
  const params = new URLSearchParams(location.search);
  const language = document.documentElement.lang.startsWith('en') ? 'en' : 'pt';
  let pageContext = {path: params.get('source') || '/', language: language, record_ids: [], term_id: params.get('term') || '', selection: []};
  if (params.get('record_id')) pageContext.record_ids = [params.get('record_id')];
  let state = {conversations: [], active: null};
  let lastCitation = null, activeRequest = null, liveLookup = new Map(), nextRequestContext = null;
  function safeSource(row) {
    if (!row || typeof row.excerpt !== 'string') return null;
    const result = {};
    ['document_id','title','excerpt','tipo_fonte','source_relative_path','sha256','record_id','updated','library_id','page_sha256','doi','reviewed_at','evidence_kind','community_id','community_slug'].forEach(k => { if (typeof row[k] === 'string') result[k] = row[k].slice(0, k === 'excerpt' ? 4000 : 400); });
    if (Number.isInteger(row.page)) result.page = row.page;
    if (Number.isInteger(row.library_version)) result.library_version = row.library_version;
    if (typeof row.url === 'string' && /^(?:\/records\/[A-Za-z0-9_-]+|\/argiloclay\/library\/[a-f0-9]{32}\/\d+\/\d+|\/communities\/[a-z0-9][a-z0-9_-]{0,199}\/about)$/.test(row.url)) result.url = row.url;
    return result;
  }
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (saved && Array.isArray(saved.conversations)) {
      state.conversations = saved.conversations.filter(c => c && typeof c.id === 'string' && Array.isArray(c.messages)).slice(0,12).map(c => ({id:c.id,title:String(c.title || text.newTitle).slice(0,100),messages:c.messages.filter(m=>m && ['user','assistant'].includes(m.role) && typeof m.content === 'string').slice(-40).map(m=>({id:String(m.id || crypto.randomUUID()),role:m.role,content:m.content.slice(0,14000),kind:['demo','rag'].includes(m.kind)?m.kind:'plain',needsVerification:Array.isArray(m.sources)&&m.sources.some(source=>source.record_id||source.library_id||source.community_id||source.tipo_fonte==='comunidade_invenio'),sources:Array.isArray(m.sources)?m.sources.slice(0,12).map(safeSource).filter(Boolean):[],limitations:Array.isArray(m.limitations)?m.limitations.filter(v=>typeof v==='string').slice(0,8):[]}))}));
      state.active = state.conversations.some(c=>c.id===saved.active)?saved.active:null;
    }
  } catch (_) { /* The conversation also works without session storage. */ }
  function current() { return state.conversations.find(c=>c.id===state.active); }
  function save() {
    try {
      while (JSON.stringify(state).length > 1500000 && state.conversations.length > 1) state.conversations.pop();
      sessionStorage.setItem(storageKey, JSON.stringify(state));
    } catch (_) { status.textContent=text.sessionError; }
  }
  function createConversation() { const c={id:crypto.randomUUID(),title:text.newTitle,messages:[]};state.conversations.unshift(c);state.conversations=state.conversations.slice(0,12);state.active=c.id;return c; }
  function setSourcesFlag(value) { app.dataset.sourcesOpen=String(value);toggleSources.setAttribute('aria-expanded',String(value)); }
  function closeSources() { if(sources.open)sources.close();setSourcesFlag(false); }
  function openSources(focus) { if(!sources.open){if(narrow.matches)sources.showModal();else sources.show();}setSourcesFlag(true);if(focus)app.querySelector('[data-close-sources]').focus(); }
  sources.addEventListener('close',()=>{setSourcesFlag(sources.open);if(!sources.open && lastCitation?.isConnected)lastCitation.focus();});
  narrow.addEventListener('change',()=>{if(sources.open){sources.close();openSources(false);}});
  function renderHistory() {
    const list=history.querySelector('[data-history-list]');list.replaceChildren();
    const rows=state.conversations.filter(c=>c.messages.length);
    if(!rows.length){const p=document.createElement('p');p.textContent=text.emptyHistory;list.append(p);}
    rows.forEach(c=>{const b=document.createElement('button');b.type='button';b.textContent=c.title;b.addEventListener('click',()=>{cancelPending();state.active=c.id;history.hidePopover();closeSources();render();save();});list.append(b);});
  }
  function literalAnswer(slot, message) {
    const pattern=/\[(?:Fonte|Source) (\d+)\]/g;let cursor=0,match;
    while((match=pattern.exec(message.content))){
      slot.append(document.createTextNode(message.content.slice(cursor,match.index)));
      const number=Number(match[1]);
      if(message.sources?.[number-1]){const b=document.createElement('button');b.type='button';b.className='chat-citation';b.dataset.citation=message.id+'-'+number;b.textContent=String(number);b.setAttribute('aria-label',text.source+' '+number);slot.append(b);}else slot.append(document.createTextNode(match[0]));
      cursor=pattern.lastIndex;
    }
    slot.append(document.createTextNode(message.content.slice(cursor)));
  }
  function renderSources(rows) {
    const live=app.querySelector('[data-live-sources]');live.replaceChildren();liveLookup=new Map();
    rows.filter(m=>m.kind==='rag'&&!m.needsVerification).forEach(m=>(m.sources||[]).forEach((source,i)=>liveLookup.set(m.id+'-'+(i+1),source)));
    const demo=rows.some(m=>m.kind==='demo');
    app.querySelector('[data-demo-sources]').hidden=!demo || liveLookup.size>0;
    app.querySelector('[data-sources-empty]').hidden=demo || liveLookup.size>0;
    app.querySelector('[data-source-count]').textContent=String(liveLookup.size || (demo?2:0));
    live.hidden=!liveLookup.size;
    const list=document.createElement('div');list.className='chat-source-list';live.append(list);
    liveLookup.forEach((source,key)=>{
      const button=document.createElement('button');button.type='button';button.className='chat-source-item';button.dataset.source=key;button.setAttribute('aria-pressed','false');
      const caption=document.createElement('span');const title=document.createElement('strong');title.textContent=source.title||source.document_id;const small=document.createElement('small');small.textContent=[source.tipo_fonte,source.page?text.page+' '+source.page:'',source.record_id||''].filter(Boolean).join(' · ');caption.append(title,small);button.append(caption);list.append(button);
      const detail=document.createElement('section');detail.className='chat-source-detail';detail.dataset.sourceDetail=key;detail.tabIndex=-1;detail.hidden=true;
      const h=document.createElement('h3');h.textContent=source.title||text.source;const quote=document.createElement('blockquote');quote.textContent=source.excerpt;
      const dl=document.createElement('dl');
      [[text.identifier,source.document_id],[text.origin,source.source_relative_path],['SHA-256',source.sha256],[text.updated,source.reviewed_at||source.updated],['DOI',source.doi],[(language==='pt'?'Versão':'Version'),source.library_version]].forEach(([label,value])=>{if(!value)return;const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;dl.append(dt,dd);});
      detail.append(h,quote,dl);
      if(source.url){const a=document.createElement('a');a.className='chat-support-link';a.href=source.url;a.target='_blank';a.rel='noopener';a.textContent=source.library_id?(language==='pt'?'Abrir página da fonte':'Open source page'):source.community_id?(language==='pt'?'Sobre a comunidade':'About the community'):text.openRecord;detail.append(a);}
      live.append(detail);
    });
    const first=liveLookup.keys().next().value;if(first)selectSource(first,false);
  }
  function relatedQuestions(question, sources) {
    const en=language==='en', q=question.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/argiloinerais|argilomienerais/g,'argilominerais'), choices=[];
    const add=(pt,english)=>choices.push({question:en?english:pt});
    if(/argilominer|clay minerals?/.test(q)){
      add('O que são argilas?','What are clays?');add('O que é caulinita?','What is kaolinite?');
    }else if(/argilas?|\bclays?\b/.test(q)){
      add('O que são argilominerais?','What are clay minerals?');add('O que são argilas e indique registros relacionados do acervo?','What are clays and suggest related publications from the collection?');
    }else if(/caulin|kaolin|caulim/.test(q)){
      add('Explique a caulinita e as tendências de pesquisa no acervo.','Explain kaolinite and research trends in the collection.');add('O que são argilominerais?','What are clay minerals?');
    }else if(/esmect|smect/.test(q)){
      add('Explique as esmectitas e indique registros relacionados do acervo.','Explain smectites and suggest related publications from the collection.');add('O que é caulinita?','What is kaolinite?');
    }else if(/meunier|clays/i.test(sources.map(s=>s.title).join(' '))){
      add('O que são argilas?','What are clays?');add('O que são argilominerais?','What are clay minerals?');
    }
    const record=sources.find(s=>s.record_id && /^[A-Za-z0-9_-]{1,100}$/.test(s.record_id));
    if(record)choices.push({question:en?'Summarize this record.':'Resuma este registro.',label:(en?'What does this publication discuss? ':'O que esta publicação apresenta? ')+(record.title||record.record_id),record_id:record.record_id});
    if(!choices.length){const book=sources.find(s=>s.library_id&&s.title);if(book)choices.push({question:(en?'Do you know ':'Você conhece ')+book.title.slice(0,200)+'?'});}
    return choices.filter(item=>item.question.toLowerCase().replace(/[?.]/g,'')!==question.toLowerCase().replace(/[?.]/g,'')).slice(0,3);
  }
  function render() {
    const rows=current()?.messages||[];messages.replaceChildren();
    app.querySelector('[data-welcome]').hidden=rows.length>0;app.querySelector('[data-session-actions]').hidden=!rows.length;
    rows.forEach((m,index)=>{
      const id=m.role==='user'?'chat-user-template':m.kind==='demo'?'chat-demo-template':'chat-assistant-template';
      const node=document.getElementById(id).content.cloneNode(true),slot=node.querySelector('[data-message-text]');
      if(slot){if(m.needsVerification)slot.textContent=text.verifyingHistory;else if(m.kind==='rag')literalAnswer(slot,m);else slot.textContent=m.content;}
      if(m.limitations?.length){const ul=document.createElement('ul');ul.className='chat-demo-note';m.limitations.forEach(value=>{const li=document.createElement('li');li.textContent=value;ul.append(li);});node.querySelector('article').append(ul);}
      if(index===rows.length-1 && m.role==='assistant' && m.kind==='rag' && !m.needsVerification && !activeRequest){
        const list=relatedQuestions(rows[index-1]?.content||'',m.sources||[]);
        if(list.length){const group=document.createElement('div');group.className='chat-answer-followups';group.setAttribute('aria-label',language==='pt'?'Perguntas relacionadas':'Related questions');
          list.forEach(item=>{const b=document.createElement('button');b.type='button';b.dataset.suggestion='';b.dataset.question=item.question;if(item.record_id)b.dataset.recordId=item.record_id;b.textContent=item.label||item.question;group.append(b);});node.querySelector('article').append(group);}
      }
      messages.append(node);
    });
    renderSources(rows);renderHistory();updateInput();verifyConversation(current());
  }
  async function verifyConversation(conversation) {
    if(!conversation || conversation.verifying)return;
    const pending=conversation.messages.filter(m=>m.needsVerification);
    if(!pending.length)return;
    conversation.verifying=true;
    const references=new Map();pending.forEach(m=>m.sources.filter(s=>s.record_id).forEach(s=>references.set(s.record_id+'|'+s.updated,{record_id:s.record_id,updated:s.updated||''})));
    const libraryRefs=new Map();pending.forEach(m=>m.sources.filter(s=>s.library_id).forEach(s=>libraryRefs.set(s.document_id,{document_id:s.document_id,library_id:s.library_id,library_version:s.library_version,page:s.page,sha256:s.sha256,page_sha256:s.page_sha256})));
    const communityRefs=new Map();pending.forEach(m=>m.sources.filter(s=>s.community_id).forEach(s=>communityRefs.set(s.document_id,{document_id:s.document_id,community_id:s.community_id,community_slug:s.community_slug,updated:s.updated,sha256:s.sha256})));
    const rows=Array.from(references.values()),pdfRows=Array.from(libraryRefs.values()),communityRows=Array.from(communityRefs.values()),allowed=new Set(),allowedPdf=new Set(),allowedCommunity=new Set();
    try {
      for(let start=0;start<Math.max(rows.length,pdfRows.length,communityRows.length);start+=12){
        const response=await fetch(text.verifyUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':text.csrfToken},body:JSON.stringify({records:rows.slice(start,start+12),library_sources:pdfRows.slice(start,start+12),community_sources:communityRows.slice(start,start+12)}),signal:AbortSignal.timeout(8000)});
        if(!response.ok)throw new Error();const result=await response.json();
        result.verified.forEach(s=>allowed.add(s.record_id+'|'+s.updated));
        (result.library_verified||[]).forEach(id=>allowedPdf.add(id));
        (result.community_verified||[]).forEach(id=>allowedCommunity.add(id));
      }
    } catch (_) { /* A cached record is never displayed without current access verification. */ }
    pending.forEach(m=>{if(m.sources.some(s=>(s.record_id&&!allowed.has(s.record_id+'|'+s.updated))||(s.library_id&&!allowedPdf.has(s.document_id))||(s.community_id&&!allowedCommunity.has(s.document_id))||(s.tipo_fonte==='comunidade_invenio'&&!s.community_id))){m.sources=[];m.content=text.staleHistory;m.kind='plain';m.limitations=[];}m.needsVerification=false;});
    conversation.verifying=false;save();if(current()===conversation)render();
  }
  function updateInput(){app.dataset.busy=String(!!activeRequest);app.querySelector('[data-cancel-request]').hidden=!activeRequest;app.querySelectorAll('[data-suggestion]').forEach(b=>b.disabled=!!activeRequest);send.disabled=!!activeRequest||!input.value.trim();app.querySelector('[data-char-count]').textContent=input.value.length+'/2000';app.querySelector('[data-composer]').setAttribute('aria-busy',String(!!activeRequest));}
  function scrollBottom(){const el=app.querySelector('[data-chat-scroll]');el.scrollTop=el.scrollHeight;}
  const preparing = language==='pt'?'Preparando uma explicação em português… As fontes já estão disponíveis.':'Preparing an explanation… Sources are already available.';
  const keptEvidence = language==='pt'?'Não consegui concluir uma explicação confiável. As fontes continuam disponíveis no botão Fontes.':'I could not complete a reliable explanation. Source pages remain available in Sources.';
  function jobUrl(key){return text.jobUrlPattern.replace('__JOB__',encodeURIComponent(key));}
  function cancelJob(request){if(request.jobId)fetch(jobUrl(request.jobId),{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':text.csrfToken},keepalive:true}).catch(()=>{});}
  function cancelPending(){if(!activeRequest)return;cancelJob(activeRequest);activeRequest.controller.abort();activeRequest.message.content=text.cancelled;activeRequest.message.limitations=activeRequest.fallback?.limitations||[];activeRequest.message.needsVerification=activeRequest.message.sources.some(s=>s.record_id||s.library_id||s.community_id||s.tipo_fonte==='comunidade_invenio');status.textContent=text.cancelled;activeRequest=null;}
  function applyAnswer(answer,data){answer.content=data.answer.slice(0,14000);answer.kind='rag';answer.sources=data.sources.slice(0,12).map(safeSource).filter(Boolean);answer.limitations=(data.limitations||[]).filter(v=>typeof v==='string').slice(0,8);answer.toolsUsed=data.tools_used;}
  function pause(ms,signal){return new Promise((resolve,reject)=>{const timer=setTimeout(done,ms);function done(){signal.removeEventListener('abort',abort);resolve();}function abort(){clearTimeout(timer);reject(new Error('aborted'));}signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();});}
  async function submit(event){
    event.preventDefault();const value=input.value.trim().slice(0,2000);if(!value||activeRequest)return;const requestContext=nextRequestContext||pageContext;nextRequestContext=null;
    const c=current()||createConversation();if(!c.messages.length)c.title=value.slice(0,80);
    const answer={id:crypto.randomUUID(),role:'assistant',content:text.loading,kind:'plain',sources:[],limitations:[]};
    c.messages.push({id:crypto.randomUUID(),role:'user',content:value,kind:'plain'},answer);c.messages=c.messages.slice(-40);
    const requestState={controller:new AbortController(),message:answer};activeRequest=requestState;input.value='';render();scrollBottom();status.textContent=text.loading;
    const timer=setTimeout(()=>requestState.controller.abort(),text.jobsUrl?110000:10000);
    try{
      const response=await fetch(text.jobsUrl||text.queryUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':text.csrfToken},body:JSON.stringify({question:value,context:requestContext}),signal:requestState.controller.signal});
      let data=await response.json();
      if(!response.ok||data.available!==true||!Array.isArray(data.sources)||typeof data.answer!=='string')throw new Error('unavailable');
      if(activeRequest!==requestState){if(data.generation?.job_id){requestState.jobId=data.generation.job_id;cancelJob(requestState);}return;}
      applyAnswer(answer,data);requestState.fallback=data;save();
      if(data.generation?.state==='pending'){
        requestState.jobId=data.generation.job_id;answer.limitations.push(preparing);status.textContent=preparing;render();scrollBottom();
        while(activeRequest===requestState){
          await pause(750,requestState.controller.signal);
          const poll=await fetch(jobUrl(requestState.jobId),{credentials:'same-origin',headers:{'X-CSRFToken':text.csrfToken},signal:requestState.controller.signal});
          if(!poll.ok)throw new Error('poll_failed');
          const result=await poll.json();if(activeRequest!==requestState)return;
          if(result.generation?.state==='pending')continue;
          applyAnswer(answer,result);requestState.jobId=null;
          if(result.generation?.state!=='complete')answer.limitations.push(keptEvidence);
          break;
        }
      }
      if(data.generation?.state==='fallback' && data.generation.reason!=='disabled')answer.limitations.push(keptEvidence);
      status.textContent=answer.sources.length?text.sent:text.noEvidence;
    }catch(_){if(activeRequest!==requestState)return;cancelJob(requestState);if(requestState.fallback){if(requestState.fallback.sources.some(s=>s.record_id)){answer.content=text.staleHistory;answer.sources=[];answer.limitations=[];}else{applyAnswer(answer,requestState.fallback);answer.limitations.push(keptEvidence);}status.textContent=keptEvidence;}else{answer.content=text.unavailable;status.textContent=text.unavailable;}}
    finally{clearTimeout(timer);if(activeRequest===requestState){activeRequest=null;render();save();scrollBottom();input.focus();}}
  }
  window.addEventListener('pagehide',()=>{if(activeRequest)cancelJob(activeRequest);});
  app.querySelector('[data-composer]').addEventListener('submit',submit);
  app.querySelector('[data-cancel-request]').addEventListener('click',()=>{cancelPending();render();save();input.focus();});
  input.addEventListener('input',updateInput);
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!send.disabled)app.querySelector('[data-composer]').requestSubmit();}});
  const welcome=app.querySelector('[data-welcome]');
  app.addEventListener('click',event=>{const b=event.target.closest('[data-suggestion]');if(!b||b.disabled||activeRequest)return;nextRequestContext=b.dataset.recordId?{...pageContext,record_ids:[b.dataset.recordId],selection:[],term_id:''}:null;input.value=b.dataset.question;updateInput();app.querySelector('[data-composer]').requestSubmit();});
  // A finite greeting, replayed only for a new conversation. No animation runs offscreen.
  function greet(){welcome.classList.remove('chat-greeting');requestAnimationFrame(()=>{if(!document.hidden&&!welcome.hidden)welcome.classList.add('chat-greeting');});}
  function syncVisibility(){app.dataset.motionPaused=String(document.hidden);}
  document.addEventListener('visibilitychange',syncVisibility);syncVisibility();
  new IntersectionObserver(entries=>{entries.forEach(entry=>{if(entry.target===welcome)welcome.dataset.offscreen=String(!entry.isIntersecting);});},{root:app.querySelector('[data-chat-scroll]')}).observe(welcome);
  app.querySelector('[data-new-chat]').addEventListener('click',()=>{cancelPending();createConversation();input.value='';closeSources();render();save();app.querySelector('[data-chat-scroll]').scrollTop=0;greet();input.focus();});
  app.querySelector('[data-demo]').addEventListener('click',()=>{cancelPending();const c=createConversation();c.title=text.demoTitle;c.messages=[{id:crypto.randomUUID(),role:'user',content:text.demoQuestion,kind:'plain'},{id:crypto.randomUUID(),role:'assistant',content:'',kind:'demo'}];render();save();app.querySelector('[data-chat-scroll]').scrollTop=0;if(!narrow.matches)openSources(false);});
  toggleSources.addEventListener('click',()=>{lastCitation=null;if(sources.open)closeSources();else openSources(true);});
  app.querySelector('[data-close-sources]').addEventListener('click',()=>{closeSources();toggleSources.focus();});
  function selectSource(value,focus){app.querySelectorAll('[data-source-detail]').forEach(el=>el.hidden=el.dataset.sourceDetail!==value);app.querySelectorAll('[data-source]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.source===value)));if(focus){const detail=Array.from(app.querySelectorAll('[data-source-detail]')).find(el=>el.dataset.sourceDetail===value);detail?.focus();}}
  sources.addEventListener('click',event=>{const b=event.target.closest('[data-source]');if(b)selectSource(b.dataset.source,false);});
  messages.addEventListener('click',async event=>{const citation=event.target.closest('[data-citation]');if(citation){lastCitation=citation;openSources(false);selectSource(citation.dataset.citation,true);return;}const copy=event.target.closest('[data-copy]');if(!copy)return;const answer=copy.closest('article').cloneNode(true);answer.querySelectorAll('button:not([data-citation])').forEach(b=>b.remove());try{await navigator.clipboard.writeText(answer.innerText||answer.textContent);status.textContent=text.copied;}catch(_){status.textContent=text.copyError;}});
  app.querySelector('[data-export]').addEventListener('click',()=>{const c=current();if(!c?.messages.length)return;const demo=document.getElementById('chat-demo-template').content.cloneNode(true);demo.querySelectorAll('button').forEach(b=>b.remove());const lines=[text.exportTitle,text.exportNote,'',c.title,''];c.messages.forEach(m=>{if(m.needsVerification){lines.push(text.assistant+':',text.verifyingHistory,'');return;}lines.push((m.role==='user'?text.user:text.assistant)+':',m.kind==='demo'?demo.textContent.trim():m.content,'');(m.sources||[]).forEach(s=>lines.push(JSON.stringify(s)));(m.limitations||[]).forEach(v=>lines.push(v));});const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='argiloclay-conversa.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  if(params.get('context') && /^[a-f0-9-]{36}$/.test(params.get('context')) && window.BroadcastChannel){const channel=new BroadcastChannel('argiloclay-context-'+params.get('context'));channel.onmessage=event=>{if(event.data?.type==='page-context' && Array.isArray(event.data.context?.selection)){pageContext.selection=event.data.context.selection.slice(0,6);}};channel.postMessage({type:'request-context'});setTimeout(()=>channel.close(),30000);}
  note.textContent=text.connected+' '+text.context+': '+pageContext.path;
  fetch(text.statusUrl,{credentials:'same-origin',signal:AbortSignal.timeout(8000)}).then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{note.textContent=(data.partial?(language==='pt'?'Consulta direta às fontes públicas da Argiloteca disponível.':'Direct access to Argiloteca’s public sources is available.'):(data.available?text.connected:text.unavailable))+' '+text.context+': '+pageContext.path;}).catch(()=>{note.textContent=text.unavailable;});
  render();if(current()?.messages.length)scrollBottom();greet();
})();
