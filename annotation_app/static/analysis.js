export function initializeAnalysis(state, api) {
  const panel = document.createElement('details');
  panel.className = 'science-panel';
  panel.innerHTML = `<summary>Vue et mesures</summary>
    <div class="science-body">
    <div class="science-filters">
      <label>Périmètre <select id="science-scope"><option value="image">Mosaïque entière</option><option value="zone">Tuile sélectionnée</option></select></label>
      <label>Mesurer <select id="science-source"><option value="annotations">Tracés enregistrés</option><option value="automatic">Axes automatiques calculés</option></select></label>
      <label><input id="science-validated" type="checkbox"> Limiter aux tuiles validées</label>
      <details><summary>Règle de superposition</summary>
        <label>Tolérance <select id="science-tolerance"><option value="0">0 px — exact uniquement</option><option value="1">1 px</option><option value="2" selected>2 px</option><option value="3">3 px</option><option value="5">5 px</option></select></label>
        <p>Les portions parallèles qui se recouvrent dans cette tolérance comptent une fois.</p>
      </details>
    </div>
    <nav class="science-tabs" aria-label="Vue et mesures"><button data-tab="layers" aria-pressed="true">Couches</button><button data-tab="lengths" aria-pressed="false">Bilan</button><button data-tab="figures" aria-pressed="false">Figures</button></nav>
    <section data-section="layers">
      <label>Afficher <select id="science-layer"><option value="">Image seule</option><option value="centerline">Axes automatiques finaux</option><option value="skeleton">Squelette</option><option value="mask">Masque seuillé</option><option value="score">Score automatique</option><option value="cost">Coût automatique</option><option value="route_cost">Coût du tracé manuel</option></select></label>
      <label>Opacité <input id="science-opacity" type="range" min="0" max="100" value="65"></label>
      <label><input id="science-axes" type="checkbox"> Superposer les axes du bilan</label>
      <div id="science-categories"></div>
      <button id="science-prepare">Calculer les couches du périmètre</button><button id="science-cancel">Arrêter</button>
      <p id="science-progress" role="status"></p>
      <details><summary>Exporter les couches</summary><button id="science-mask-export">PNG affiché</button><button id="science-array-export">Masques numériques ZIP</button></details>
      <p>Le choix des couches est identique pour une tuile et pour la mosaïque. Les zones transparentes ne sont pas calculées.</p>
    </section>
    <section data-section="lengths" hidden>
      <button id="science-refresh">Actualiser</button>
      <div id="science-results" aria-live="polite">Chargement du bilan…</div>
      <p>Les tracés partageant une portion sont regroupés pour le compteur.</p>
    </section>
    <section data-section="figures" hidden>
      <label>Figure <select id="science-figure"><option value="lengths">Longueurs par catégorie</option><option value="map">Carte des axes</option><option value="spatial">Longueur par tuile</option><option value="orientation">Orientation des axes</option></select></label>
      <label><input id="science-background" type="checkbox" checked> Fond MEB</label>
      <button id="science-preview">Afficher</button>
      <div class="science-exports"><button data-format="png">PNG</button><button data-format="svg">SVG</button><button data-format="pdf">PDF</button><button data-format="csv">CSV</button></div>
      <img id="science-preview-image" alt="Figure des axes du bilan" hidden>
      <p></p>
    </section><p id="science-error" role="alert"></p></div>`;
  document.querySelector('.canvas-shell').append(panel);
  const el = id => document.getElementById(`science-${id}`);
  panel.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{
    panel.querySelectorAll('[data-tab]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    panel.querySelectorAll('[data-section]').forEach(section=>section.hidden=section.dataset.section!==button.dataset.tab);
  });
  document.getElementById('open-analysis').onclick=()=>{panel.open=!panel.open;};
  let overview = null, detail = [], generation = 0, timer = null, reportRequest = 0;
  const labels = {open:'Non colmatée', filled:'Colmatée', mixed:'Mixte', uncertain:'Incertaine', unclassified:'Non classée', conflict:'Conflit'};
  const colors = {open:'#d43d2f',filled:'#087db6',mixed:'#7650a8',uncertain:'#666666',unclassified:'#d28b00',conflict:'#ff00aa'};
  let measuredOverlay=null, latestReport=null;
  el('categories').innerHTML=Object.entries(labels).map(([key,label])=>`<label style="display:inline-block;color:${colors[key]}"><input type="checkbox" data-series="${key}" checked>${label}</label>`).join(' ');
  function measuredAxes() {
    if(measuredOverlay) state.viewer?.removeOverlay(measuredOverlay);
    measuredOverlay=null;
    if(!el('axes').checked || !latestReport || !state.viewer?.world.getItemCount()) return;
    const enabled=new Set([...el('categories').querySelectorAll('input:checked')].map(e=>e.dataset.series));
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox',`0 0 ${state.metadata.width} ${state.metadata.height}`);
    svg.setAttribute('preserveAspectRatio','none');
    svg.style.pointerEvents='none';
    for(const [category,color] of Object.entries(colors)) {
      if(!enabled.has(category)) continue;
      const path=document.createElementNS(svg.namespaceURI,'path');
      path.setAttribute('d',latestReport.segments.filter(s=>s.category===category).map(s=>`M${s.geometry[0].join(',')}L${s.geometry[1].join(',')}`).join(''));
      path.setAttribute('stroke',color); path.setAttribute('fill','none'); path.setAttribute('stroke-width','2'); path.setAttribute('vector-effect','non-scaling-stroke'); svg.append(path);
    }
    state.viewer.addOverlay({element:svg,location:state.viewer.world.getItemAt(0).imageToViewportRectangle(0,0,state.metadata.width,state.metadata.height),checkResize:false});
    measuredOverlay=svg;
  }
  el('axes').onchange=measuredAxes;
  el('categories').onchange=measuredAxes;
  const fmt = value => new Intl.NumberFormat('fr-FR', {maximumFractionDigits:1}).format(value);
  function query() {
    const params = new URLSearchParams({validated: el('validated').checked, source:el('source').value, tolerance_px:el('tolerance').value});
    if (el('scope').value === 'zone') {
      if (!state.selectedZoneId) throw new Error('Sélectionner une tuile.');
      params.set('zone_id', state.selectedZoneId);
    }
    return params;
  }
  function safe(fn) { return async () => { try { el('error').textContent=''; await fn(); } catch(error) { el('error').textContent=error.message; } }; }
  // Ce qui determine reellement les surcouches affichees. Tant que cela ne
  // change pas, les redessiner ne sert a rien : la vue peut bouger, l'image
  // d'ensemble et les tuiles de detail restent les memes. Les redessiner a
  // chaque fin d'animation les faisait disparaitre puis revenir, et relancait
  // un rendu serveur d'une seconde.
  let shownSignature = null;
  function clearLayers() {
    generation++;
    if (overview) state.viewer?.removeOverlay(overview);
    detail.forEach(item => state.viewer?.removeOverlay(item));
    overview=null; detail=[];
    shownSignature=null;   // plus rien a l'ecran : le prochain rendu s'impose
  }
  async function showLayers(force = false) {
    const kind = el('layer').value;
    if (!kind || !state.viewer?.world.getItemCount()) { clearLayers(); shownSignature = null; return; }
    // Affecte APRES `clearLayers()`, qui incremente `generation` : sinon
    // chaque image chargee se croit perimee et n'est jamais posee.
    let current;
    const opacity = Number(el('opacity').value)/100;
    function add(url, rectangle, isDetail=false) {
      const img = new Image(); img.style.opacity=opacity; img.style.pointerEvents='none';
      img.onload=()=>{
        if (generation !== current) return;
        state.viewer.addOverlay({element:img, location:rectangle, checkResize:false});
        if(isDetail) detail.push(img); else overview=img;
      };
      img.onerror=()=>{if (generation===current) el('error').textContent='Impossible de charger la couche.';};
      img.src=url;
    }
    const image = state.viewer.world.getItemAt(0);
    const validated = el('validated').checked;
    if(el('scope').value==='zone') {
      const zone=state.zones.find(z=>z.id===state.selectedZoneId);
      if(!zone) return;
      const signature=`zone|${kind}|${zone.id}|${validated}`;
      if(!force && signature===shownSignature) return;
      clearLayers(); shownSignature=signature; current=generation;
      add(`/api/analysis/layers/${kind}.png?zone_id=${zone.id}&validated=${validated}`,image.imageToViewportRectangle(zone.x,zone.y,zone.width,zone.height));
      return;
    }
    const previousGeneration = generation;
    const status = await api('/api/analysis/layers/status');
    if (generation !== previousGeneration) return;   // un autre rendu a pris la main
    const bounds=image.viewportToImageRectangle(state.viewer.viewport.getBounds(true));
    const visible=state.zones.filter(z=>z.x<bounds.x+bounds.width && z.x+z.width>bounds.x && z.y<bounds.y+bounds.height && z.y+z.height>bounds.y);
    const detailed=visible.length<=6?visible.filter(z=>status.cached_zone_ids.includes(z.id) && (!validated || z.status==='done')):[];
    const exclude=detailed.map(z=>z.id).join(',');
    const signature=`mosaic|${kind}|${validated}|${status.layers_signature}|${exclude}`;
    if(!force && signature===shownSignature) return;
    clearLayers(); shownSignature=signature; current=generation;
    // `layers_signature` remplace un horodatage : l'URL ne change que si une
    // tuile vient d'etre calculee, donc le navigateur reutilise l'image.
    add(`/api/analysis/layers/${kind}.png?exclude=${exclude}&validated=${validated}&v=${status.layers_signature}`, image.imageToViewportRectangle(0,0,state.metadata.width,state.metadata.height));
    for(const zone of detailed) {
      add(`/api/analysis/layers/${kind}.png?zone_id=${zone.id}&validated=${validated}`, image.imageToViewportRectangle(zone.x,zone.y,zone.width,zone.height), true);
    }
  }
  let cachedCount=-1;
  async function progress() {
    const status=await api('/api/analysis/layers/status');
    el('progress').textContent=`${status.cached_zone_ids.length} tuiles en cache · ${status.completed}/${status.total} dans cette tâche · ${status.running?'calcul en cours':status.cancelled?'arrêté':'au repos'} · ${status.errors.length} erreur(s)`;
    if(status.errors.length) el('error').textContent=status.errors.map(e=>`Tuile ${e.zone_id}: ${e.message}`).join(' ; ');
    if(status.cached_zone_ids.length!==cachedCount) {cachedCount=status.cached_zone_ids.length; await showLayers();}
    if(status.running) timer=setTimeout(safe(progress),4000);
    else { timer=null; await showLayers(); }
  }
  el('layer').onchange=safe(async()=>{await showLayers(); if(!timer) await progress();});
  el('opacity').oninput=()=>{for(const img of [overview,...detail]) if(img) img.style.opacity=Number(el('opacity').value)/100;};
  el('prepare').onclick=safe(async()=>{await api(`/api/analysis/layers/prepare?${query()}`,{method:'POST'}); if(timer) clearTimeout(timer); await progress();});
  el('cancel').onclick=safe(async()=>{await api('/api/analysis/layers/cancel',{method:'POST'});});
  async function refresh() {
    const request=++reportRequest;
    el('results').textContent='Calcul…';
    const result=await api(`/api/analysis/lengths?${query()}`);
    if(request!==reportRequest) return;
    latestReport=result; measuredAxes();
    const missing=result.unprocessed_zone_ids.length;
    const noData=result.source==='automatic' && !result.zones.length;
    el('results').innerHTML=`<div class="science-totals"><strong>${noData?'Non calculé':fmt(result.total_px)+' px'}</strong><span>Longueur cumulée</span></div>
      <p>${result.raw_trace_count} tracés enregistrés · ${fmt(result.overlap_removed_px)} px de superposition retirés à ${result.tolerance_px} px de tolérance.</p>
      <table><thead><tr><th>Catégorie</th><th>Longueur (px)</th></tr></thead><tbody>${Object.entries(labels).map(([key,label])=>`<tr><td>${label}</td><td>${noData?'—':fmt(result.length_px[key])}</td></tr>`).join('')}</tbody></table>
      <p>Part colmatée parmi ouvert + colmaté : ${result.filled_fraction===null?'non définie':fmt(100*result.filled_fraction)+' %'}.</p>
      <p>${result.zones.length} tuile(s) incluse(s)${missing?' · '+missing+' non calculée(s), exclue(s)':''}.</p>`;
    if(result.overlap_groups.length) {
      const review=document.createElement('details');
      const summary=document.createElement('summary');summary.textContent='Tracés regroupés (identifiants)';review.append(summary);
      for(const ids of result.overlap_groups) {const row=document.createElement('p');row.textContent=ids.join(' / ');review.append(row);}
      el('results').append(review);
    }
  }
  el('refresh').onclick=safe(refresh);
  for(const id of ['scope','validated','source','tolerance']) el(id).onchange=safe(async()=>{
    latestReport=null; measuredAxes(); el('preview-image').hidden=true;
    await refresh(); await showLayers();
  });
  let refreshTimer;
  window.addEventListener('crack-data-changed',()=>{
    if(!panel.open) {latestReport=null; return;}
    clearTimeout(refreshTimer); refreshTimer=setTimeout(safe(refresh),250);
    el('preview-image').hidden=true;
  });
  window.addEventListener('crack-zone-changed',()=>{
    if(el('scope').value==='zone') {clearLayers(); latestReport=null; measuredAxes(); if(panel.open) {safe(refresh)();safe(showLayers)();}}
  });
  function figureUrl(format) {
    const params=query(); params.set('kind',el('figure').value); params.set('background',el('background').checked);
    return `/api/analysis/${format==='csv'?'export.csv':`figure.${format}`}?${params}`;
  }
  el('preview').onclick=safe(async()=>{el('preview-image').src=figureUrl('png'); el('preview-image').hidden=false;});
  el('preview-image').onerror=()=>{el('error').textContent='Erreur de génération de la figure.';};
  panel.querySelectorAll('[data-format]').forEach(button=>button.onclick=safe(async()=>{
    const response=await fetch(figureUrl(button.dataset.format));
    if(!response.ok) throw new Error((await response.json()).detail || 'Export impossible');
    const url=URL.createObjectURL(await response.blob()); const a=document.createElement('a');
    a.href=url; a.download=`lignes-centrales-${el('figure').value}.${button.dataset.format}`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  }));
  el('mask-export').onclick=safe(async()=>{
    if(!el('layer').value) throw new Error('Choisir une couche à exporter.');
    window.open(`/api/analysis/layers/${el('layer').value}.png?${query()}`, '_blank', 'noopener');
  });
  el('array-export').onclick=safe(async()=>{
    const params=new URLSearchParams({validated:el('validated').checked});
    if(el('scope').value==='zone') {
      if(!state.selectedZoneId) throw new Error('Sélectionner une tuile.');
      params.set('zone_id',state.selectedZoneId);
    }
    const status=await api('/api/analysis/layers/status');
    const needed=state.zones.filter(z=>(el('scope').value!=='zone'||z.id===state.selectedZoneId)&&(!el('validated').checked||z.status==='done')).map(z=>z.id);
    if(needed.some(id=>!status.cached_zone_ids.includes(id))) throw new Error('Calculer les couches du périmètre avant l’export ZIP.');
    const a=document.createElement('a'); a.href=`/api/analysis/masks.zip?${params}`; a.download='analysis-masks.zip'; a.click();
  });
  let viewTimer;
  const attach=()=>state.viewer.addHandler('animation-finish',()=>{
    clearTimeout(viewTimer); viewTimer=setTimeout(safe(showLayers),250);
  });
  const wait=setInterval(()=>{if(state.viewer){clearInterval(wait);attach();}},200);
  panel.addEventListener('toggle',safe(async()=>{if(panel.open){await refresh(); if(!timer) await progress();}}));
}
