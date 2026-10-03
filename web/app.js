/** 101XVC BRAIN browser client. Dependency-free; no records leave this instance. */
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { page: 'overview', stats: {}, sources: [], watchlist: [], registry: [], scout: [], offset: 0, limit: 20, total: 0, categories: new Set(), currentProperty: null, importRecords: [], importColumns: [], editingSource: null };
const categories = [
  { key: 'assessor', title: 'Assessor', color: '#ef9a63', label: 'ASSESSOR RECORDS' },
  { key: 'recorder', title: 'Recorder', color: '#e08176', label: 'RECORDER + TITLE' },
  { key: 'zoning', title: 'Zoning', color: '#a798ce', label: 'ZONING + LAND USE' },
  { key: 'market', title: 'Market', color: '#cd91ac', label: 'MARKET SIGNALS' },
];
const stateNames = { AL:'Alabama', AK:'Alaska', AZ:'Arizona', AR:'Arkansas', CA:'California', CO:'Colorado', CT:'Connecticut', DE:'Delaware', FL:'Florida', GA:'Georgia', HI:'Hawaii', ID:'Idaho', IL:'Illinois', IN:'Indiana', IA:'Iowa', KS:'Kansas', KY:'Kentucky', LA:'Louisiana', ME:'Maine', MD:'Maryland', MA:'Massachusetts', MI:'Michigan', MN:'Minnesota', MS:'Mississippi', MO:'Missouri', MT:'Montana', NE:'Nebraska', NV:'Nevada', NH:'New Hampshire', NJ:'New Jersey', NM:'New Mexico', NY:'New York', NC:'North Carolina', ND:'North Dakota', OH:'Ohio', OK:'Oklahoma', OR:'Oregon', PA:'Pennsylvania', RI:'Rhode Island', SC:'South Carolina', SD:'South Dakota', TN:'Tennessee', TX:'Texas', UT:'Utah', VT:'Vermont', VA:'Virginia', WA:'Washington', WV:'West Virginia', WI:'Wisconsin', WY:'Wyoming', DC:'District of Columbia' };
const fieldDefinitions = [
  ['address','Street address',['address','property_address','street_address','site_address','situs_address']],
  ['parcel_id','Parcel identifier',['parcel_id','parcel','apn','account','account_number']],
  ['owner','Owner',['owner','owner_name','taxpayer']],
  ['state','State',['state','state_code','property_state']],
  ['county_fips','County FIPS',['county_fips','fips','fips_code']],
  ['assessed_value','Assessed value',['assessed_value','assessment','total_assessed_value']],
  ['estimated_value','Estimated value',['estimated_value','market_value','arv','value']],
  ['debt','Debt',['debt','mortgage_balance','loan_balance']],
  ['zoning','Zoning',['zoning','zone','land_use']],
  ['latitude','Latitude',['latitude','lat']],
  ['longitude','Longitude',['longitude','lon','lng']],
];

function element(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = String(value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'value') node.value = value;
    else if (key === 'disabled') node.disabled = Boolean(value);
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
function replace(selector, ...children) { const target = typeof selector === 'string' ? $(selector) : selector; target.replaceChildren(...children.flat().filter(Boolean)); }
function number(value) { const parsed = typeof value === 'string' ? Number(value.replace(/[$,%\s,]/g,'')) : Number(value); return Number.isFinite(parsed) ? parsed : 0; }
function money(value, compact = false) {
  if (value === null || value === undefined || value === '') return 'Unavailable';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0, ...(compact ? { notation: 'compact' } : {}) }).format(number(value));
}
function count(value) { return new Intl.NumberFormat('en-US').format(number(value)); }
function date(value) { if (!value) return 'Not recorded'; const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }); }
function textValue(value, fallback = 'Unavailable') { if (value === null || value === undefined || value === '') return fallback; return typeof value === 'object' ? JSON.stringify(value) : String(value); }
function items(response) { return Array.isArray(response) ? response : response?.items || []; }
function scoreValue(value) { return Math.max(0, Math.min(100, number(value))); }
function score(value) { const val = scoreValue(value); return element('div', { class:'score-display' }, element('span',{class:'score-value',text:value == null ? '—' : val.toFixed(0)}),element('span',{class:'score-meter'},element('span',{style:`width:${val}%` }))); }
function synthetic(record) { return record?.synthetic === true || record?.synthetic === 1 || record?.synthetic === '1'; }
function tag(label, type = '') { return element('span',{class:`tag ${type}`,text:label}); }
function recordTag(record) { return synthetic(record) ? tag('SYNTHETIC', '') : tag('IMPORTED','blue'); }
function empty(title, description, action) { return element('div',{class:'empty-state'},element('div',{class:'empty-symbol',text:'◈'}),element('h3',{text:title}),element('p',{text:description}),action); }
function tableEmpty(body, title, description, columns) { replace(body,element('tr',{},element('td',{colspan:columns},empty(title,description)))); }
function loading(target) { replace(target,element('div',{class:'loading',text:'Loading workspace data'})); }
function toast(message, error = false) { const note = element('div',{class:`toast${error ? ' error' : ''}`,role:error ? 'alert' : 'status',text:message}); $('#toast-stack').append(note); setTimeout(() => note.remove(), 6000); }
function apiError(error) { toast(error.message || 'The request could not be completed.',true); }
async function api(path, options = {}) {
  const token = sessionStorage.getItem('brain-api-token');
  const headers = new Headers(options.headers || {});
  if (token) headers.set('Authorization',`Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `${response.status}: ${response.statusText}`;
    try { const data = await response.json(); message = data.error?.message || data.error || data.detail || message; } catch { /* non-JSON error */ }
    if (response.status === 401 || response.status === 403) {
      $('#connection-status').textContent = 'Access token required';
      $('#connection-detail').textContent = 'Set token in workspace settings';
      $('#connection-dot').classList.add('offline');
    }
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  if (response.status === 204) return {};
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response.text();
}
async function actionButton(button, task, busyLabel = 'Working…') {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = busyLabel;
  try { await task(); } catch (error) { apiError(error); } finally { button.disabled = false; button.textContent = original; }
}
function dialog(id) { const node = $(id); if (!node.open) node.showModal(); }
function safeLink(url, label, attrs = {}) { try { const parsed = new URL(url,location.href); if (!['https:','http:'].includes(parsed.protocol)) return element('span',{...attrs,text:label}); return element('a',{...attrs,href:parsed.href,target:'_blank',rel:'noopener noreferrer',text:label}); } catch { return element('span',{...attrs,text:label}); } }

function navigate() {
  const requested = location.hash.slice(1) || 'overview';
  const page = ['overview','registry','scout','sources','watchlist','knowledge','operations'].includes(requested) ? requested : 'overview';
  state.page = page;
  $$('.page').forEach(node => node.classList.toggle('active',node.id === `page-${page}`));
  $$('.nav-link').forEach(node => node.classList.toggle('active',node.dataset.page === page));
  $('#breadcrumb-page').textContent = {registry:'PROPERTY REGISTRY',sources:'SOURCE NETWORK',scout:'DEAL SCOUT',watchlist:'WATCHLIST',knowledge:'KNOWLEDGE VAULT',operations:'OPERATIONS',overview:'OVERVIEW'}[page];
  $('.sidebar').classList.remove('mobile-open');
  const loaders = { overview: loadOverview, registry: loadRegistry, scout: loadScout, sources: loadSources, watchlist: loadWatchlist, knowledge: loadKnowledge, operations: loadOperations };
  loaders[page]().catch(apiError);
}
async function loadHealth() {
  try {
    const health = await api('/api/health');
    const okay = ['ok','healthy','ready','degraded'].includes(health.status) || health.status === true;
    $('#connection-status').textContent = okay ? 'Instance connected' : textValue(health.status,'Instance connected');
    $('#connection-detail').textContent = health.status === 'degraded' ? 'Some services unavailable' : 'Local property intelligence';
    $('#connection-dot').classList.toggle('offline',!okay);
    renderServices(health);
    return health;
  } catch (error) {
    $('#connection-status').textContent = 'Instance unavailable';
    $('#connection-detail').textContent = 'Check server and access token';
    $('#connection-dot').classList.add('offline');
    throw error;
  }
}
function renderServices(health) {
  let services = health.services || {};
  if (!Array.isArray(services)) services = Object.entries(services).map(([name,value]) => ({name,...(typeof value === 'object' ? value : {status:value})}));
  if (!services.length) services = [{name:'Python API',status:health.status,description:'Local orchestration + property store'}];
  replace('#service-cards',services.map(service => {
    const status = textValue(service.status ?? service.available ?? service.healthy,'unknown');
    const isOkay = ['ok','healthy','ready','running','online','true'].includes(status);
    return element('article',{class:'service-card'},element('div',{class:'service-card-top'},element('b',{text:service.name || service.service || 'Service'}),tag(status.toUpperCase(),isOkay ? 'green' : 'muted')),element('p',{text:service.description || service.detail || service.version || 'Status reported by the local service.'}));
  }));
}
async function loadStats() {
  state.stats = await api('/api/stats');
  const syntheticCount = number(state.stats.synthetic_count ?? state.stats.synthetic_properties);
  const hasSynthetic = syntheticCount > 0 || state.stats.synthetic === true || state.stats.demo_mode === true;
  $('#synthetic-indicator').classList.toggle('hidden',!hasSynthetic);
  renderStateFilters();
  return state.stats;
}
function renderStateFilters() {
  const all = stateCounts();
  for (const selector of ['#registry-state','#scout-state']) {
    const node = $(selector), chosen = node.value;
    replace(node,element('option',{value:'',text:'All states'}),all.map(([code]) => element('option',{value:code,text:`${code} · ${stateNames[code] || code}`})));
    node.value = chosen;
  }
}
function stateCounts() {
  const input = state.stats.state_counts || {};
  if (Array.isArray(input)) return input.map(row => [row.state || row.code || 'Unknown',number(row.count ?? row.total)]).sort((a,b)=>b[1]-a[1]);
  return Object.entries(input).map(([code,value])=>[code,number(value)]).sort((a,b)=>b[1]-a[1]);
}
function categoryCount(key) {
  const source = state.stats.category_counts || {};
  if (Array.isArray(source)) return number(source.find(row => row.category === key)?.count);
  return number(source[key]);
}
async function loadOverview() {
  const [stats, opportunities] = await Promise.all([loadStats(),api('/api/scout?min_profit=0&limit=5')]);
  const statData = [
    ['Resolved properties',stats.properties,'◈','Across connected property records'],
    ['Evidence records',stats.evidence,'⌘','Original source records preserved'],
    ['Connected sources',stats.sources,'⌖','Configured evidence sources'],
    ['Open field conflicts',stats.conflicts,'⚑','Review competing source values'],
  ];
  replace('#stat-grid',statData.map(([title,value,symbol,foot])=>element('article',{class:'stat-card'},element('div',{class:'stat-top'},element('span',{text:title}),element('span',{class:'stat-symbol',text:symbol})),element('div',{class:'stat-value',text:count(value)}),element('div',{class:'stat-foot',text:foot}))));
  renderFusion();
  const markets = stateCounts().slice(0,5);
  const max = Math.max(1,...markets.map(row=>row[1]));
  replace('#market-coverage',markets.length ? markets.map(([code,value])=>element('div',{class:'market-row'},element('div',{class:'market-row-top'},element('span',{class:'market-row-state'},element('span',{class:'state-code',text:code}),stateNames[code] || code),element('span',{text:`${count(value)} properties`})),element('div',{class:'market-bar'},element('span',{style:`width:${value/max*100}%`})))) : empty('No markets yet','Import records to see your market footprint.'));
  const rows = items(opportunities).slice(0,5);
  if (rows.some(synthetic)) $('#synthetic-indicator').classList.remove('hidden');
  if (!rows.length) tableEmpty('#overview-opportunities','Your next opportunity starts here','Import a property dataset or load labeled synthetic data to explore the workspace.',6);
  else replace('#overview-opportunities',rows.map(property=>element('tr',{},element('td',{},propertyLabel(property)),element('td',{text:property.state || '—'}),element('td',{text:money(property.estimated_value)}),element('td',{},score(property.score ?? property.opportunity_score)),element('td',{},recordTag(property)),element('td',{},element('button',{class:'row-open','aria-label':`Open ${property.address || 'property'}`,onclick:()=>openProperty(property.id)},'↗')))));
}
function renderFusion() {
  if (!state.categories.size) categories.forEach(category=>state.categories.add(category.key));
  $('#fusion-record-title').textContent = number(state.stats.properties) ? `${count(state.stats.properties)} resolved properties` : 'Your property universe';
  $('#fusion-record-count').textContent = number(state.stats.evidence) ? `${count(state.stats.evidence)} evidence records` : 'Ready to ingest';
  replace('#category-controls',categories.map(category=>element('button',{class:`category-button ${state.categories.has(category.key) ? '' : 'inactive'}`,'aria-pressed':state.categories.has(category.key),onclick:()=>{
    if (state.categories.has(category.key)) state.categories.delete(category.key); else state.categories.add(category.key);
    drawFusion();
    $$('.category-button').forEach((button,index)=>{button.classList.toggle('inactive',!state.categories.has(categories[index].key));button.setAttribute('aria-pressed',String(state.categories.has(categories[index].key)));});
  }},element('span',{class:'category-label'},element('span',{class:'legend-dot',style:`background:${category.color}`}),category.title),element('b',{text:count(categoryCount(category.key))}))));
  drawFusion();
}
function svgNode(tagName,attributes) { const node = document.createElementNS('http://www.w3.org/2000/svg',tagName); for (const [key,value] of Object.entries(attributes)) node.setAttribute(key,String(value)); return node; }
function drawFusion() {
  const lines = [], dots = [];
  for (let categoryIndex=0;categoryIndex<categories.length;categoryIndex++) {
    const category=categories[categoryIndex], active=state.categories.has(category.key);
    for (let dotIndex=0;dotIndex<16;dotIndex++) {
      const x=32+(dotIndex%5)*31+((categoryIndex%2)*10), y=45+categoryIndex*55+Math.floor(dotIndex/5)*8;
      const cx=389, cy=129+categoryIndex*14;
      const opacity=active ? .22 + (dotIndex%4)*.08 : .025;
      lines.push(svgNode('path',{d:`M ${x+5} ${y} C ${220+dotIndex*2} ${y}, 308 ${cy}, ${cx} ${cy}`,fill:'none',stroke:category.color,'stroke-width':.65,opacity}));
      dots.push(svgNode('circle',{cx:x,cy:y,r:dotIndex%4===0 ? 3.3 : 2.1,fill:category.color,opacity:active ? .5+(dotIndex%3)*.17 : .08}));
    }
  }
  $('#fusion-lines').replaceChildren(...lines);
  $('#fusion-dots').replaceChildren(...dots);
}
function propertyLabel(property) { return element('div',{class:'table-property'},element('b',{text:property.address || 'Unaddressed property'}),element('small',{text:`Parcel ${property.parcel_id || 'unassigned'}${property.county_fips ? ` · FIPS ${property.county_fips}` : ''}`})); }
async function loadRegistry() {
  const query = new URLSearchParams({q:$('#registry-search').value,state:$('#registry-state').value,limit:String(state.limit),offset:String(state.offset)});
  const response = await api(`/api/properties?${query}`);
  state.registry = items(response); state.total = number(response.total ?? state.registry.length);
  $('#registry-count').textContent = `${count(state.total)} properties`;
  $('#registry-page-info').textContent = state.total ? `${count(state.offset+1)}–${count(Math.min(state.offset+state.limit,state.total))} of ${count(state.total)}` : 'No records';
  $('#registry-prev').disabled = state.offset === 0;
  $('#registry-next').disabled = state.offset + state.limit >= state.total;
  if (state.registry.some(synthetic)) $('#synthetic-indicator').classList.remove('hidden');
  if (!state.registry.length) return tableEmpty('#registry-rows','No matching properties','Try a broader search or import records from Source network.',7);
  replace('#registry-rows',state.registry.map(property=>{
    const risk = scoreValue(property.risk_score);
    return element('tr',{},element('td',{},propertyLabel(property)),element('td',{text:property.owner || 'Not reported'}),element('td',{text:property.state || '—'}),element('td',{text:money(property.estimated_value)}),element('td',{},element('span',{class:`risk ${risk<35 ? 'low' : risk<65 ? 'medium' : 'high'}`,text:property.risk_score == null ? '—' : `${risk.toFixed(0)} / 100`})),element('td',{},score(property.score)),element('td',{},element('button',{class:'row-open','aria-label':`Open ${property.address || 'property'}`,onclick:()=>openProperty(property.id)},'↗')));
  }));
}
async function loadScout() {
  const query = new URLSearchParams({state:$('#scout-state').value,min_profit:$('#scout-profit').value || '0'});
  state.scout = items(await api(`/api/scout?${query}`));
  if (!state.scout.length) return replace('#scout-cards',empty('No opportunities match these filters','Lower the minimum profit, choose another state, or ingest additional records.'));
  replace('#scout-cards',state.scout.slice(0,100).map((property,index)=>propertyCard(property,index+1)));
  if (state.scout.some(synthetic)) $('#synthetic-indicator').classList.remove('hidden');
}
function propertyCard(property, rank, watchlistId) {
  const profit = property.gross_profit ?? property.estimated_profit ?? property.underwriting?.gross_profit;
  const watched = state.watchlist.some(row=>(row.property_id || row.property?.id)===property.id);
  const watchButton = watchlistId ? element('button',{class:'watch-button',onclick:event=>actionButton(event.currentTarget,async()=>{await api(`/api/watchlist/${encodeURIComponent(watchlistId)}`,{method:'DELETE'});await loadWatchlist();toast('Property removed from watchlist.');})},'Remove') : element('button',{class:`watch-button${watched ? ' active' : ''}`,onclick:event=>{const button=event.currentTarget;actionButton(button,async()=>{await saveWatch(property.id);button.classList.add('active');},'Saving…').then(()=>{if(button.classList.contains('active'))button.textContent='★ Saved';});}},watched ? '★ Saved' : '☆ Watch');
  return element('article',{class:'property-card'},element('div',{class:'property-card-head'},element('div',{},element('div',{class:'property-card-rank',text:rank ? `OPPORTUNITY ${String(rank).padStart(2,'0')} · ${property.state || 'USA'}` : `SAVED PROPERTY · ${property.state || 'USA'}`}),element('h3',{text:property.address || 'Unaddressed property'}),element('p',{class:'property-subtitle',text:`${property.owner || 'Owner unavailable'} · Parcel ${property.parcel_id || 'unassigned'}`})),recordTag(property)),element('div',{class:'property-card-metrics'},element('div',{},element('span',{text:'EST. PROPERTY VALUE'}),element('b',{text:money(property.estimated_value,true)})),element('div',{},element('span',{text:'EST. GROSS PROFIT'}),element('b',{text:money(profit,true)})),element('div',{},element('span',{text:'OPPORTUNITY SCORE'}),score(property.score ?? property.opportunity_score))),element('div',{class:'property-card-actions'},element('button',{class:'button small',onclick:()=>openProperty(property.id)},'Review intelligence ↗'),watchButton));
}
async function saveWatch(propertyId) {
  await api('/api/watchlist',{method:'POST',body:JSON.stringify({property_id:propertyId})});
  state.watchlist = items(await api('/api/watchlist'));
  toast('Property saved to watchlist.');
}
async function loadWatchlist() {
  state.watchlist = items(await api('/api/watchlist'));
  if (!state.watchlist.length) return replace('#watchlist-cards',empty('Keep your best leads in view','Open a property in the registry or deal scout, then save it to your watchlist.',element('a',{class:'button',href:'#scout'},'Explore opportunities →')));
  const cards = await Promise.all(state.watchlist.map(async row=>{
    let property = row.property || row;
    if (!property.address && row.property_id) { try { property=(await api(`/api/properties/${encodeURIComponent(row.property_id)}`)).property; } catch { property={id:row.property_id,address:'Property no longer available'}; } }
    return propertyCard(property,null,row.id);
  }));
  replace('#watchlist-cards',cards);
}
async function ensureSources() { state.sources=items(await api('/api/sources')); renderSourceSelects(); return state.sources; }
function renderSourceSelects() {
  for (const selector of ['#ingest-source','#job-source']) {
    const node=$(selector), chosen=node.value;
    replace(node,element('option',{value:'',text:state.sources.length ? 'Select an evidence source' : 'Configure a source first'}),state.sources.map(source=>element('option',{value:source.id,text:source.name || source.id})));
    if (state.sources.some(source=>String(source.id)===chosen)) node.value=chosen;
    else if (state.sources.length===1) node.value=state.sources[0].id;
  }
}
async function loadSources() {
  await ensureSources();
  const counts=[['TOTAL SOURCES',state.sources.length],['CONFIGURED SOURCES',state.sources.filter(source=>source.status==='configured').length],['SOURCE CATEGORIES',new Set(state.sources.map(source=>source.category)).size]];
  replace('#source-summary',counts.map(([label,value])=>element('div',{class:'source-summary-item'},element('b',{text:count(value)}),element('span',{text:label}))));
  if (!state.sources.length) return replace('#source-cards',empty('Connect the first piece of evidence','Configure a source and upload records to begin resolving your property universe.',element('button',{class:'button primary',onclick:()=>openSource()},'+ Configure source')));
  replace('#source-cards',state.sources.map(source=>{
    const category=categories.find(item=>item.key===source.category);
    return element('article',{class:'source-card'},element('div',{class:'source-card-top'},element('span',{class:'source-card-icon',style:`color:${category?.color || '#ef9a63'}`},'⌘'),tag(textValue(source.status,'configured').toUpperCase(),source.status==='configured' ? 'green' : 'muted')),element('h3',{text:source.name || 'Unnamed source'}),element('p',{class:'source-card-meta',text:`${category?.title || source.category || 'Other'} · ${source.adapter || 'manual'} adapter · ${source.state || 'National'}${source.county_fips ? ` / ${source.county_fips}` : ''}`}),source.url ? safeLink(source.url,source.url,{class:'source-card-url'}) : element('span',{class:'source-card-url',text:'Manual dataset uploads'}),element('div',{class:'source-card-foot'},element('span',{text:source.last_run ? `Last run ${date(source.last_run)}` : source.status==='planned' ? 'Collection disabled' : 'Ready for ingestion'}),element('button',{class:'button small',onclick:()=>openSource(source)},'Configure')));
  }));
}
function openSource(source) {
  state.editingSource=source || null;
  const form=$('#source-form');form.reset();
  $('h2',form).textContent=source ? 'Configure evidence source' : 'Add an evidence source';
  $('button[type=submit]',form).textContent=source ? 'Save changes' : 'Save source';
  if (source) for (const name of ['name','category','adapter','state','county_fips','url','status']) if (form.elements.namedItem(name)) form.elements.namedItem(name).value=source[name] || '';
  const oldDelete=$('#source-delete'); if (oldDelete) oldDelete.remove();
  if (source) $('.modal-actions',form).prepend(element('button',{class:'button danger',id:'source-delete',type:'button',onclick:event=>actionButton(event.currentTarget,async()=>{
    if (!confirm(`Delete source configuration “${source.name}”? Sources with retained evidence or job history cannot be deleted.`)) return;
    await api(`/api/sources/${encodeURIComponent(source.id)}`,{method:'DELETE'});$('#source-dialog').close();await loadSources();toast('Source configuration deleted.');
  })},'Delete source'));
  dialog('#source-dialog');
}
async function openImport() {
  await ensureSources();
  if (!state.sources.length) { toast('Configure an evidence source before importing records.');openSource();return; }
  state.importRecords=[];state.importColumns=[];
  $('#ingest-form').reset();$('#ingest-file-label').textContent='Choose CSV or JSON';$('#ingest-row-count').textContent='';$('#ingest-submit').disabled=true;replace('#ingest-mapping');renderSourceSelects();dialog('#ingest-dialog');
}
export function parseCSV(text) {
  const rows=[];let row=[],field='',quoted=false;
  const data=text.replace(/^\uFEFF/,'');
  for (let i=0;i<data.length;i++) {
    const char=data[i];
    if (quoted) { if (char==='"' && data[i+1]==='"') {field+='"';i++;} else if (char==='"') quoted=false; else field+=char; }
    else if (char==='"' && field==='') quoted=true;
    else if (char===',') {row.push(field);field='';}
    else if (char==='\n' || char==='\r') {if (char==='\r' && data[i+1]==='\n') i++;row.push(field);if(row.some(value=>value.trim()!=='')) rows.push(row);row=[];field='';}
    else field+=char;
  }
  if (quoted) throw new Error('CSV contains an unclosed quoted field.');
  if (field || row.length) {row.push(field);if(row.some(value=>value.trim()!=='')) rows.push(row);}
  if (rows.length<2) throw new Error('CSV needs a header row and at least one property record.');
  const headers=rows.shift().map((value,index)=>value.trim() || `column_${index+1}`);
  if (new Set(headers).size!==headers.length) throw new Error('CSV column names must be unique.');
  return rows.map(values=>Object.fromEntries(headers.map((header,index)=>[header,values[index] || ''])));
}
async function parseImportFile() {
  const file=$('#ingest-file').files[0]; if(!file) return;
  if(file.size>10*1024*1024) throw new Error('Choose a dataset under 10 MB. Larger imports can use the command-line ingestion tools.');
  const content=await file.text();let records;
  if(file.name.toLowerCase().endsWith('.json')) {
    const parsed=JSON.parse(content);
    records=Array.isArray(parsed) ? parsed : parsed.records || parsed.items || parsed.features?.map(feature=>({...feature.properties,latitude:feature.geometry?.coordinates?.[1],longitude:feature.geometry?.coordinates?.[0]}));
    if(!Array.isArray(records)) throw new Error('JSON must be an array of records, or contain a records/items array.');
  } else records=parseCSV(content);
  records=records.filter(record=>record && typeof record==='object' && !Array.isArray(record));
  if(!records.length) throw new Error('The dataset contains no usable property records.');
  state.importRecords=records;state.importColumns=[...new Set(records.slice(0,100).flatMap(Object.keys))];
  $('#ingest-file-label').textContent=file.name;$('#ingest-row-count').textContent=`${count(records.length)} records detected`;
  $('#ingest-submit').disabled=false;
  const mappings=fieldDefinitions.map(([key,title,aliases])=>{
    return element('label',{},title,element('select',{name:`map_${key}`},element('option',{value:'',text:'Do not import this field'}),state.importColumns.map(column=>element('option',{value:column,text:column})))) ;
  });
  replace('#ingest-mapping',element('h3',{class:'mapping-heading',text:'Map your dataset columns'}),element('div',{class:'mapping-grid'},mappings));
  for(const [key,,aliases] of fieldDefinitions) {const guessed=state.importColumns.find(column=>aliases.includes(column.toLowerCase().replace(/\s+/g,'_'))) || '';$('#ingest-form').elements.namedItem(`map_${key}`).value=guessed;}
}
async function ingestRecords() {
  const form=$('#ingest-form'), sourceId=form.elements.namedItem('source_id').value;
  const map=Object.fromEntries(fieldDefinitions.map(([key])=>[key,form.elements.namedItem(`map_${key}`).value]));
  if(!map.address) throw new Error('Map the street address field so records can be resolved.');
  const source=state.sources.find(item=>String(item.id)===sourceId);
  if(!map.state && !source?.state) throw new Error('Map the state column or configure the source state.');
  if(!map.county_fips && !source?.county_fips) throw new Error('Map the county FIPS column or configure the source county FIPS.');
  const records=state.importRecords.map(raw=>{
    const mapped={_raw_record:raw};
    for(const [key,column] of Object.entries(map)) if(column && raw[column]!==undefined && raw[column]!=='') mapped[key]=['assessed_value','estimated_value','debt','latitude','longitude'].includes(key) ? number(raw[column]) : String(raw[column]);
    if(mapped.state) mapped.state=mapped.state.toUpperCase();
    mapped.synthetic=$('#ingest-synthetic').checked;
    return mapped;
  });
  if(records.length>10000)throw new Error('Split this dataset into imports of at most 10,000 records.');
  const body=JSON.stringify({source_id:sourceId,records,synthetic:$('#ingest-synthetic').checked});
  if(new TextEncoder().encode(body).byteLength>16*1024*1024)throw new Error('Mapped records exceed the 16 MB API limit. Split the dataset into smaller imports.');
  const result=await api('/api/ingest',{method:'POST',body});
  const rejected=number(result.rejected);
  if(rejected && !number(result.ingested ?? result.accepted ?? result.processed)) throw new Error(`No records ingested. ${rejected} rejected. ${textValue(result.errors?.[0]?.error || result.errors?.[0]?.message || result.errors?.[0],'Review required identifiers and mapped field values.')}`);
  $('#ingest-dialog').close();toast(`Ingestion complete. ${count(result.ingested ?? result.accepted ?? result.inserted ?? result.processed ?? records.length)} accepted${rejected ? `, ${count(rejected)} rejected` : ''}.`,rejected>0);
  await loadStats();navigate();
}
async function loadOperations() {
  const responses=await Promise.allSettled([loadHealth(),ensureSources(),api('/api/jobs'),api('/api/activity'),api('/api/models')]);
  const jobs=responses[2].status==='fulfilled' ? items(responses[2].value) : [];
  const activity=responses[3].status==='fulfilled' ? items(responses[3].value) : [];
  replace('#job-list',jobs.length ? jobs.slice(0,50).map(job=>element('div',{class:'job-row'},element('div',{},element('b',{text:job.source_name || state.sources.find(source=>source.id===job.source_id)?.name || `Job ${job.id || ''}`}),element('small',{text:`${date(job.created_at || job.started_at)} · ${count(job.records_processed ?? job.record_count ?? job.processed)} records`}),job.error ? element('small',{text:textValue(job.error)}) : null),tag(textValue(job.status,'unknown').toUpperCase(),['completed','success','succeeded'].includes(job.status) ? 'green' : ['failed','error'].includes(job.status) ? 'red' : 'muted'))) : empty('No ingestion jobs yet','Configure a URL source, then run a source job. Manual imports appear in the activity feed.'));
  replace('#activity-list',activity.length ? activity.slice(0,50).map(event=>element('div',{class:'activity-item'},element('span',{class:'activity-dot'}),element('div',{},element('b',{text:event.message || event.action || event.type || 'Workspace event'}),event.detail || event.details ? element('p',{text:textValue(event.detail || event.details)}) : null,element('small',{text:date(event.created_at || event.timestamp)})))) : empty('A clean activity trail','Source configurations, imports, and workspace actions will appear here.'));
  if(responses[4].status==='fulfilled') {
    const models=responses[4].value.models || items(responses[4].value);
    replace('#model-cards',models.length ? models.map(model=>element('article',{class:'model-card'},element('div',{class:'source-card-top'},element('b',{text:model.model_id || model.name || model.id || 'Local model'}),tag(model.synthetic ? 'SYNTHETIC REFERENCE' : 'USER-TRAINED',model.synthetic ? '' : 'blue')),element('p',{text:`${model.algorithm || model.type || model.task || 'Independent model'} · ${count(model.trained_on)} labeled rows · ${count(model.holdout_rows)} holdout rows`}),model.metrics ? element('p',{text:Object.entries(model.metrics).map(([key,value])=>`${key.replaceAll('_',' ')}: ${value}`).join(' · ')}) : null,element('p',{text:model.limitations || model.description || 'Review training provenance and holdout metrics before reliance.'}))) : element('article',{class:'model-card'},element('b',{text:'Local model not trained'}),element('p',{text:'Train with labeled outcome records or initialize the explicitly synthetic reference model through the local CLI.'})));
  } else replace('#model-cards',element('article',{class:'model-card'},element('b',{text:'Model status unavailable'}),element('p',{text:responses[4].reason.message})));
}
async function loadKnowledge() {
  const query=$('#knowledge-search').value.trim();
  const response=await api(`/api/knowledge?q=${encodeURIComponent(query || 'property underwriting')}`);
  const results=response.results || items(response);
  replace('#knowledge-results',results.length ? results.map(result=>element('article',{class:'knowledge-result'},element('h3',{text:result.title || result.path || 'Knowledge document'}),element('small',{text:result.path || 'Local knowledge vault'}),element('p',{text:result.snippet || result.description || 'Open this Markdown document in your local knowledge vault.'}),result.content ? element('details',{},element('summary',{text:'Read document'}),element('pre',{class:'detail-mono',text:result.content})) : null)) : empty('No matching knowledge documents',query ? 'Try a broader search such as underwriting, identity, or provenance.' : 'The local vault is ready for your operating guides and research.'));
}
async function openProperty(id) {
  if(id===null || id===undefined) return toast('This record has no property identifier.',true);
  const drawer=$('#property-drawer');drawer.classList.remove('hidden');$('#drawer-backdrop').classList.remove('hidden');document.body.style.overflow='hidden';loading('#drawer-content');$('#drawer-close').focus();
  try {
    const data=await api(`/api/properties/${encodeURIComponent(id)}`);const property=data.property || data;state.currentProperty=property;
    const evidence=data.evidence || [], conflicts=data.conflicts || [], comps=data.comps || [];
    const detailFields=[['Parcel identifier',property.parcel_id],['Owner',property.owner],['State',property.state],['County FIPS',property.county_fips],['Assessed value',money(property.assessed_value)],['Estimated value',money(property.estimated_value)],['Reported debt',money(property.debt)],['Zoning',property.zoning],['Opportunity score',property.score==null ? 'Unavailable' : `${scoreValue(property.score).toFixed(0)} / 100`],['Risk score',property.risk_score==null ? 'Unavailable' : `${scoreValue(property.risk_score).toFixed(0)} / 100`],['Updated',date(property.updated_at)]];
    const body=element('div',{class:'drawer-body'},recordTag(property),element('h2',{class:'drawer-title',id:'drawer-title',text:property.address || 'Unaddressed property'}),element('p',{class:'drawer-subtitle',text:`${stateNames[property.state] || property.state || 'Market unavailable'} · ${count(evidence.length)} evidence records · ${count(conflicts.length)} field conflicts`}),element('div',{class:'drawer-actions'},element('button',{class:'button primary',onclick:event=>actionButton(event.currentTarget,()=>saveWatch(property.id),'Saving…')},'☆ Add to watchlist'),element('button',{class:'button',onclick:()=>{closeDrawer();location.hash='scout';const form=$('#underwriting-form');form.elements.arv.value=number(property.estimated_value);form.elements.purchase_price.value=number(data.underwriting?.purchase_price ?? property.debt ?? property.assessed_value);toast('Property values loaded into underwriting desk. Review all assumptions.');}},'Test economics ↗')),element('section',{class:'drawer-section'},element('h3',{text:'Resolved property fields'}),element('div',{class:'detail-grid'},detailFields.map(([title,value])=>element('div',{class:'detail-item'},element('span',{text:title}),element('b',{text:textValue(value)}))))));
    if(data.underwriting) body.append(element('section',{class:'drawer-section'},element('h3',{text:'Estimated deal economics'}),element('div',{class:'detail-grid'},Object.entries(data.underwriting).filter(([key])=>['gross_profit','company_share','max_offer','qualifies','purchase_price','arv'].includes(key)).map(([key,value])=>element('div',{class:'detail-item'},element('span',{text:key.replaceAll('_',' ')}),element('b',{text:typeof value==='boolean' ? (value ? 'Meets threshold' : 'Below threshold') : money(value)}))))));
    body.append(element('section',{class:'drawer-section'},element('h3',{text:'Source evidence + provenance'}),evidence.length ? evidence.map(row=>renderEvidence(row)) : element('p',{class:'form-note',text:'No evidence payloads were supplied for this property.'})));
    const provenance=data.field_provenance || data.provenance || property.provenance || property.field_provenance;
    if(provenance) body.append(element('section',{class:'drawer-section'},element('h3',{text:'Field provenance map'}),element('pre',{class:'detail-mono',text:JSON.stringify(provenance,null,2)})));
    body.append(element('section',{class:'drawer-section'},element('h3',{text:'Competing field values'}),conflicts.length ? conflicts.map(conflict=>element('div',{class:'conflict-card'},element('b',{text:conflict.field || conflict.field_name || 'Field conflict'}),element('p',{text:conflict.message || conflict.description || JSON.stringify(conflict.values || conflict,null,2)}))) : element('p',{class:'form-note',text:'No competing field values recorded.'})));
    body.append(element('section',{class:'drawer-section'},element('h3',{text:'Candidate comparable records'}),element('p',{class:'form-note',text:'Registry candidates ranked by value similarity. Verify sale date, condition, location, and comparability.'}),comps.length ? comps.map(comp=>element('div',{class:'comp-card'},element('div',{},element('b',{text:comp.address || comp.parcel_id || 'Comparable property'}),element('small',{text:comp.distance_miles!=null ? `${number(comp.distance_miles).toFixed(1)} miles · ${comp.state || ''}` : comp.status || comp.state || 'Record-based comparison'})),element('b',{text:money(comp.sale_price ?? comp.estimated_value ?? comp.price)}))) : element('p',{class:'form-note',text:'No comparable records available. Ingest local market evidence to improve coverage.'})));
    replace('#drawer-content',body);
  } catch(error) {replace('#drawer-content',empty('Property could not be loaded',error.message));apiError(error);}
}
function renderEvidence(row) {
  const payload=row._raw_record || row.raw_record || row.payload || row.record || row.data || row.attributes || {};
  const fields=row.fields || row.normalized || row.normalized_fields || row.values || row.attributes;
  const node=element('article',{class:'evidence-card'},element('div',{class:'evidence-card-head'},element('b',{text:row.source_name || row.source?.name || state.sources.find(source=>source.id===row.source_id)?.name || row.source_id || 'Evidence source'}),tag(textValue(row.category || row.source?.category,'record').toUpperCase(),'muted')),element('small',{text:`Recorded ${date(row.observed_at || row.created_at || row.ingested_at)}${row.confidence!=null ? ` · confidence ${(number(row.confidence)*100).toFixed(0)}%` : ''}`));
  if(row.source_url || row.url) node.append(safeLink(row.source_url || row.url,'Open original source ↗',{class:'text-link'}));
  if(fields) node.append(element('div',{class:'evidence-fields'},(Array.isArray(fields) ? fields : Object.keys(fields)).slice(0,20).map(field=>element('span',{class:'field-pill',text:typeof field==='object' ? field.field || JSON.stringify(field) : field}))));
  node.append(element('details',{},element('summary',{class:'form-note',text:'View original evidence'}),element('pre',{class:'detail-mono',text:typeof payload==='string' ? payload : JSON.stringify(payload,null,2)})));
  return node;
}
function closeDrawer() { $('#property-drawer').classList.add('hidden');$('#drawer-backdrop').classList.add('hidden');document.body.style.overflow='';state.currentProperty=null; }
async function calculate(event) {
  event.preventDefault();const form=event.currentTarget;
  await actionButton($('button[type=submit]',form),async()=>{
    const values=Object.fromEntries([...new FormData(form).entries()].map(([key,value])=>[key,number(value)]));
    const result=await api('/api/underwrite',{method:'POST',body:JSON.stringify(values)});
    replace('#underwriting-result',element('div',{class:'calc-output-row'},element('span',{text:'Est. gross transaction profit'}),element('b',{text:money(result.gross_profit)})),element('div',{class:'calc-output-row'},element('span',{text:'Maximum offer at target profit'}),element('b',{text:money(result.max_offer)})),element('div',{class:'calc-output-row'},element('span',{text:'Underwriting threshold'}),tag(result.qualifies ? 'MEETS THRESHOLD' : 'BELOW THRESHOLD',result.qualifies ? 'green' : 'red')),element('div',{class:'calc-output-row emphasis'},element('span',{text:'101XVC gross share'}),element('b',{text:money(result.company_share)})));
  },'Calculating…');
}

// Interaction wiring: all remote text is assigned with textContent, never HTML.
window.addEventListener('hashchange',navigate);
$('#today-label').textContent=new Date().toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'}).toUpperCase();
$('#mobile-menu').addEventListener('click',()=>$('.sidebar').classList.toggle('mobile-open'));
$('#drawer-close').addEventListener('click',closeDrawer);$('#drawer-backdrop').addEventListener('click',closeDrawer);
document.addEventListener('keydown',event=>{
  if(event.key==='Escape') {closeDrawer();$('.sidebar').classList.remove('mobile-open');}
  if(event.altKey && !event.ctrlKey && /^[1-7]$/.test(event.key)) {event.preventDefault();location.hash=['overview','registry','scout','sources','watchlist','knowledge','operations'][number(event.key)-1];}
  if(event.key==='Tab' && !$('#property-drawer').classList.contains('hidden')) {
    const focusable=$$('button,a[href],input,select,summary,[tabindex="0"]',$('#property-drawer')).filter(node=>!node.disabled);
    const first=focusable[0], last=focusable.at(-1);
    if(event.shiftKey && document.activeElement===first) {event.preventDefault();last?.focus();}
    else if(!event.shiftKey && document.activeElement===last) {event.preventDefault();first?.focus();}
  }
});
$$('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
$$('dialog').forEach(node=>node.addEventListener('click',event=>{if(event.target===node){const rect=node.getBoundingClientRect();if(event.clientX<rect.left || event.clientX>rect.right || event.clientY<rect.top || event.clientY>rect.bottom)node.close();}}));
$('#settings-open').addEventListener('click',()=>{$('#api-token').value=sessionStorage.getItem('brain-api-token') || '';dialog('#settings-dialog');});
$('#settings-form').addEventListener('submit',event=>{event.preventDefault();const token=$('#api-token').value.trim();if(token)sessionStorage.setItem('brain-api-token',token);else sessionStorage.removeItem('brain-api-token');$('#settings-dialog').close();loadHealth().then(()=>{toast('Workspace connection saved.');navigate();}).catch(apiError);});
$('#refresh-all').addEventListener('click',event=>actionButton(event.currentTarget,async()=>{await Promise.all([loadStats(),loadHealth()]);navigate();toast('Workspace refreshed.');},'↻'));
$('#seed-button').addEventListener('click',event=>actionButton(event.currentTarget,async()=>{const result=await api('/api/seed',{method:'POST',body:JSON.stringify({})});await loadStats();await ensureSources();navigate();toast(`Labeled synthetic demonstration data ${result.already_seeded ? 'already available' : 'loaded'}.`);},'Loading…'));
$('#top-ingest').addEventListener('click',()=>openImport().catch(apiError));$('#source-ingest').addEventListener('click',()=>openImport().catch(apiError));
$('#source-add-open').addEventListener('click',()=>openSource());
replace('#source-category',...categories.map(category=>element('option',{value:category.key,text:category.title})));
$('#source-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;actionButton($('button[type=submit]',form),async()=>{
  const payload=Object.fromEntries(new FormData(form));payload.state=payload.state.toUpperCase();
  const edit=state.editingSource;
  await api(edit ? `/api/sources/${encodeURIComponent(edit.id)}` : '/api/sources',{method:edit ? 'PUT' : 'POST',body:JSON.stringify(payload)});
  $('#source-dialog').close();await loadSources();toast(edit ? 'Source configuration updated.' : 'Evidence source configured.');
},'Saving…');});
$('#ingest-file').addEventListener('change',()=>parseImportFile().catch(error=>{$('#ingest-submit').disabled=true;apiError(error);}));
$('#ingest-form').addEventListener('submit',event=>{event.preventDefault();actionButton($('#ingest-submit'),ingestRecords,'Ingesting…');});
let searchTimer;
$('#registry-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.offset=0;loadRegistry().catch(apiError);},250);});
$('#registry-state').addEventListener('change',()=>{state.offset=0;loadRegistry().catch(apiError);});
$('#registry-prev').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);loadRegistry().catch(apiError);});
$('#registry-next').addEventListener('click',()=>{state.offset+=state.limit;loadRegistry().catch(apiError);});
$('#export-registry').addEventListener('click',event=>actionButton(event.currentTarget,async()=>{
  const token=sessionStorage.getItem('brain-api-token');const headers=token ? {Authorization:`Bearer ${token}`} : {};
  const response=await fetch('/api/export',{headers});if(!response.ok)throw new Error(`Export failed: ${response.status}`);
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=element('a',{href:url,download:`101XVC-BRAIN-properties-${new Date().toISOString().slice(0,10)}.csv`});document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Property registry exported.');
},'Exporting…'));
$('#scout-refresh').addEventListener('click',event=>actionButton(event.currentTarget,loadScout,'Loading…'));
$('#underwriting-form').addEventListener('submit',calculate);
$('#operations-refresh').addEventListener('click',event=>actionButton(event.currentTarget,loadOperations,'Refreshing…'));
$('#job-form').addEventListener('submit',event=>{event.preventDefault();actionButton($('button[type=submit]',event.currentTarget),async()=>{
  const sourceId=$('#job-source').value;if(!sourceId)throw new Error('Select a source to run.');await api('/api/jobs',{method:'POST',body:JSON.stringify({source_id:sourceId})});await loadOperations();toast('Source job submitted.');
},'Running…');});
$('#knowledge-form').addEventListener('submit',event=>{event.preventDefault();actionButton($('button[type=submit]',event.currentTarget),loadKnowledge,'Searching…');});
$('#extract-form').addEventListener('submit',event=>{event.preventDefault();actionButton($('button[type=submit]',event.currentTarget),async()=>{
  const result=await api('/api/extract',{method:'POST',body:JSON.stringify({text:$('#extract-text').value})});
  const entries=Object.entries(result.entities || {});
  replace('#extract-result',tag('REVIEW REQUIRED',''),entries.map(([category,values])=>element('div',{class:'extract-category'},element('b',{text:category.replaceAll('_',' ').toUpperCase()}),values.length ? element('div',{class:'evidence-fields'},values.map(value=>element('span',{class:'field-pill',text:value}))) : element('span',{class:'form-note',text:'No candidates detected.'}))));
},'Extracting…');});
$('#predict-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;actionButton($('button[type=submit]',form),async()=>{
  const features=Object.fromEntries([...new FormData(form).entries()].map(([key,value])=>[key,number(value)]));
  const result=await api('/api/predict',{method:'POST',body:JSON.stringify({features})});
  replace('#prediction-result',element('div',{class:'calc-output-row emphasis'},element('span',{text:'Estimated training-label probability'}),element('b',{text:`${(number(result.probability)*100).toFixed(1)}%`})),element('p',{class:'form-note',text:`${result.model_id || 'Local model'} · ${result.synthetic ? 'Synthetic reference training' : 'User-supplied training labels'} · ${result.limitations || ''}`}),element('details',{},element('summary',{class:'form-note',text:'Inspect feature contributions'}),element('pre',{class:'detail-mono',text:JSON.stringify(result.contributions || {},null,2)})));
},'Predicting…');});
$('#train-form').addEventListener('submit',event=>{event.preventDefault();actionButton($('button[type=submit]',event.currentTarget),async()=>{
  const file=$('#train-file').files[0];if(!file)throw new Error('Choose a labeled JSON dataset.');
  if(file.size>10*1024*1024)throw new Error('Training dataset must be under 10 MB.');
  const data=JSON.parse(await file.text());let rows=Array.isArray(data) ? data : data.rows;
  if(!Array.isArray(rows))throw new Error('Training JSON must be an array of labeled rows or an object containing rows.');
  if(data.synthetic===true)rows=rows.map(row=>({...row,synthetic:true}));
  const result=await api('/api/train',{method:'POST',body:JSON.stringify({rows,synthetic:data.synthetic===true})});await loadOperations();toast(`Local model ${result.model_id || ''} trained on ${count(result.trained_on)} labeled rows.`);
},'Training…');});
Promise.allSettled([loadHealth(),loadStats(),ensureSources()]).then(results=>{for(const result of results)if(result.status==='rejected')apiError(result.reason);navigate();});
