(() => {
  'use strict';
  const root = document.querySelector('.khtp-page');
  if (!root) return;
  const draftContext = root.dataset.draftContext;
  const $ = id => document.getElementById('khtp-' + id);
  const labels = {observed:'관찰됨',absent:'없음 확인',unobserved:'아직 관찰하지 않음',uncertain:'판단불가'};
  let job = null, busy = false, sequence = 0, dirty = {}, selected = null, preview = null;
  let subjectDirty = {};
  const subjectFields = ['name','reference','exam_date'];
  const readSubject = () => Object.fromEntries(subjectFields.map(key=>[key,$(key).value]));
  const isDirty = () => !!(Object.keys(dirty).length || Object.keys(subjectDirty).length || (!job && $('file').files.length));
  function validateSubject() {
    const value=readSubject();
    if(!value.name.trim()&&!value.reference.trim()){$('name').focus();$('status').scrollIntoView({block:'start'});throw new Error('이름 또는 관리번호 중 하나를 입력해 주세요.');}
    if([...value.name.trim()].length>100 || [...value.reference.trim()].length>100)throw new Error('이름과 관리번호는 각각 100자 이내로 입력해 주세요.');
    if(!$('exam_date').checkValidity()){$('exam_date').focus();$('status').scrollIntoView({block:'start'});throw new Error('검사일을 확인해 주세요.');}
    return value;
  }
  const clone = value => structuredClone(value);
  function node(tag, text, className) {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (className) value.className = className;
    return value;
  }
  function status(text, error = false) {
    $('status').textContent = text; $('status-bottom').textContent = text;
    for(const id of ['status','status-bottom'])$(id).classList.toggle('is-error',error);
    if(error) {
      const target=job && $('status').getBoundingClientRect().bottom<0 ? $('status-bottom') : $('status');
      target.focus();
    }
  }
  function mark(id) {
    dirty[id] = ++sequence;
    job.observations[id].author = 'user';
    status('수정한 내용이 있습니다. 저장하거나 PDF로 받아 주세요.');
  }
  function lock(value) {
    busy = value;
    for (const id of ['start','save','analyze','new','pdf','pdf-bottom','file']) $(id).disabled = value;
  }
  function requestBody() {
    return {revision:job.revision,edits:Object.fromEntries(Object.keys(dirty).map(id => [id,clone(job.observations[id])])),
      ...(Object.keys(subjectDirty).length ? {subject:validateSubject()} : {}),
      ...('person_id' in subjectDirty ? {person_id:$('person_id').value} : {})};
  }
  async function request(url, options = {}, retry = true) {
    const response = await fetch(url,{...options,headers:{...options.headers,'X-KHTP-CSRF':root.dataset.csrf,'X-KHTP-Draft-Context':draftContext}});
    if (response.headers.get('content-type')?.includes('application/pdf')) return {response};
    let data;
    try { data = await response.json(); }
    catch { throw new Error(response.status===404 ? '검사 기록에 접근할 수 없습니다. 현재 입력은 화면에 남아 있습니다.' : '응답을 읽지 못했습니다. 현재 입력은 유지됩니다. 다시 시도하세요.'); }
    if(response.status===403 && retry && options.method==='POST') {
      const refreshed=await request('/khtp/current',{},false);
      if(refreshed.response.ok && refreshed.data.csrf) {
        root.dataset.csrf=refreshed.data.csrf;
        return request(url,options,false);
      }
      return refreshed;
    }
    return {response,data};
  }
  function syncShareLink() {
    const link=$('share'),schedule=$('schedule');
    root.dataset.jobId=job?.id || '';
    if(job) {
      link.href=link.dataset.urlTemplate.replace('__job_id__',encodeURIComponent(job.id));
      link.hidden=false;
      schedule.href=`/schedule/new?kind=khtp&exam_id=${encodeURIComponent(job.id)}`;schedule.hidden=schedule.dataset.enabled!=='1';
    } else {
      link.hidden=true;
      link.removeAttribute('href');
      schedule.hidden=true;schedule.removeAttribute('href');
    }
  }
  function adopt(fresh, captured = {}, capturedSubject = {}) {
    const currentSubject=readSubject(),pendingSubject={};
    for(const key of Object.keys(subjectDirty))if(subjectDirty[key]!==capturedSubject[key])pendingSubject[key]=subjectDirty[key];
    for(const key of subjectFields)$(key).value=key in pendingSubject ? currentSubject[key] : (fresh.subject?.[key] || '');
    if(!('person_id' in pendingSubject)) {
      window.HaeseokPeople?.set('khtp-person-picker',fresh.person);
      $('person_id').value=fresh.person_id || '';
    }
    subjectDirty=pendingSubject;
    const pending = {};
    for (const id of Object.keys(dirty)) {
      if (dirty[id] !== captured[id]) pending[id] = {version:dirty[id],value:clone(job.observations[id])};
    }
    job = fresh; dirty = {};
    syncShareLink();
    for (const [id,entry] of Object.entries(pending)) { job.observations[id] = entry.value; dirty[id] = entry.version; }
    // A newer local edit must not restore a parent removed by reanalysis.
    const parents=new Set(['O2.1','O2.2','O2.3','O3.3'].flatMap(id=>job.observations[id].regions.map(region=>region.id)));
    for(const [id,row] of Object.entries(job.observations)) for(const region of row.regions) {
      if(region.parent && !parents.has(region.parent)) {region.parent=null;dirty[id]=++sequence;}
    }
    const summary=job.observations['O8.1'];
    summary.refs=summary.refs.filter(ref=>ref.reason!=='부모 귀속 미정');
    for(const [id,row] of Object.entries(job.observations)) if(/^O[345]\./.test(id) && row.state!=='absent') {
      for(const region of row.regions) if(!region.parent) summary.refs.push({item:id,region:region.id,reason:'부모 귀속 미정'});
    }
    summary.state=summary.refs.length?'uncertain':'observed';
    summary.text=summary.refs.length?`확인할 참조 ${summary.refs.length}개`:'남은 미확인 참조 없음';
    render();
  }
  function draw(id) {
    selected=id;
    if (!job) return;
    const svg=$('svg'), ns='http://www.w3.org/2000/svg';
    svg.replaceChildren(); svg.setAttribute('viewBox',`0 0 ${job.dimensions.width} ${job.dimensions.height}`);
    const image=document.createElementNS(ns,'image');
    image.setAttribute('href',job.image_url); image.setAttribute('width',job.dimensions.width); image.setAttribute('height',job.dimensions.height); svg.append(image);
    const regions=id==='extra' ? job.extras : job.observations[id]?.regions || [];
    for (const region of regions) {
      const [x1,y1,x2,y2]=region.box,rect=document.createElementNS(ns,'rect');
      for (const [k,v] of Object.entries({x:x1,y:y1,width:x2-x1,height:y2-y1})) rect.setAttribute(k,v);
      const title=document.createElementNS(ns,'title'); title.textContent=region.label || '근거 영역';rect.append(title);svg.append(rect);
    }
    $('region-caption').textContent=id ? `${id==='extra'?'나무 참고 후보':job.pack.items.find(v=>v.id===id)?.title || ''} · 표시된 영역은 후보 또는 직접 수정한 근거입니다.` : '관찰표의 ‘근거 영역’을 누르면 그림에 표시됩니다.';
    if(job.observations[id]?.state==='absent')$('region-caption').textContent='없음 확인을 검토한 범위입니다. 현재 존재의 근거가 아닙니다.';
  }
  function regionEditor(id,row) {
    const details=node('details');details.append(node('summary','근거 영역 보기·수정'));
    details.addEventListener('toggle',()=>{if(details.open) {renderRegions();draw(id);}});
    const list=node('div'); details.append(list);
    function renderRegions() {
      list.replaceChildren();
      row.regions.forEach((region,index)=>{
        const entry=node('div',undefined,'khtp-region');entry.append(node('strong',`영역 ${index+1}${row.state==='absent'?' · 없음 확인의 검토 범위 (존재 근거 아님)':''}`));
        const coords=node('div',undefined,'khtp-coordinates');
        const box=region.box;
        ['x','y','폭','높이'].forEach((title,i)=>{
          const label=node('label',title),input=node('input');input.type='number';input.step='0.1';
          input.value=[box[0],box[1],box[2]-box[0],box[3]-box[1]][i];
          input.setAttribute('aria-label',`${id} 영역${index+1} ${title}`);
          input.addEventListener('input',()=>{
            const values=[...coords.querySelectorAll('input')].map(v=>Number(v.value));
            region.box=[values[0],values[1],values[0]+values[2],values[1]+values[3]];
            region.confirmed=false;mark(id);draw(id);
            const check=entry.querySelector('input[type=checkbox]');if(check)check.checked=false;
          });label.append(input);coords.append(label);
        });entry.append(coords);
        if (['O2.1','O2.2','O2.3'].includes(id)) {
          const label=node('label'),check=node('input');check.type='checkbox';check.checked=!!region.confirmed;
          check.addEventListener('change',()=>{region.confirmed=check.checked;mark(id);});
          label.append(check,document.createTextNode('이 객체의 전체 경계를 확인함'));entry.append(label);
        } else {
          const label=node('label','연결된 객체'),select=node('select'); select.append(new Option('귀속 미정',''));
          for (const parentId of ['O2.1','O2.2','O2.3','O3.3']) job.observations[parentId].regions.forEach((parent,i)=>{
            if(parent.id!==region.id)select.append(new Option(`${job.pack.items.find(d=>d.id===parentId).title} 영역 ${i+1}`,parent.id));
          });select.value=region.parent || '';select.addEventListener('change',()=>{region.parent=select.value || null;mark(id);});
          label.append(select);entry.append(label);
        }
        const remove=node('button','영역 삭제','button small');remove.type='button';remove.addEventListener('click',()=>{
          row.regions.splice(index,1);mark(id);
          for(const [otherId,other] of Object.entries(job.observations)) for(const child of other.regions) if(child.parent===region.id){child.parent=null;mark(otherId);}
          renderRegions();draw(id);
        });entry.append(remove);list.append(entry);
      });
      if(!row.regions.length)list.append(node('p','아직 기록된 영역이 없습니다. 그림을 보며 필요한 경우만 추가하세요.'));
    }
    renderRegions();
    const add=node('button','근거 영역 추가','button small');add.type='button';add.addEventListener('click',()=>{
      row.regions.push({id:'u'+crypto.randomUUID().replaceAll('-',''),box:[0,0,Math.min(100,job.dimensions.width),Math.min(100,job.dimensions.height)],parent:null,confirmed:false,label:'직접 입력'});mark(id);renderRegions();draw(id);
    });details.append(add);
    if(row.author==='user' && row.candidates.length) details.append(node('p',`재분석 후보 ${row.candidates.length}곳은 직접 수정한 영역과 별도로 보존했습니다.`));
    return details;
  }
  function render() {
    const opened=new Set([...document.querySelectorAll('.khtp-group[open]')].map(v=>v.dataset.group));
    $('upload').hidden=true;$('work').hidden=false;$('pdf').hidden=false;$('sources').hidden=false;
    const groups=$('groups');groups.replaceChildren();
    for (const group of job.pack.groups) {
      const definitions=job.pack.items.filter(d=>d.id.split('.')[0]===group.id);
      const detail=node('details',undefined,'khtp-group');detail.dataset.group=group.id;detail.open=opened.has(group.id);
      const summary=node('summary'),title=node('strong',group.title), brief=node('span',undefined,'khtp-summary');
      const unresolved=definitions.filter(d=>job.observations['O8.1'].refs.some(ref=>ref.item===d.id)).length;
      const edited=definitions.filter(d=>job.observations[d.id].author==='user').length;
      brief.textContent=group.id==='O8'?job.observations['O8.1'].text : `${definitions.length}개 항목${unresolved?' · 확인 필요 '+unresolved+'개':''}${edited?' · 직접 수정 '+edited+'개':''}`;
      if(group.id!=='O8') {
        const snippets=definitions.map(d=>job.observations[d.id].text).filter(Boolean);
        brief.textContent+='\n'+(snippets.length?snippets.slice(0,2).map(v=>v.slice(0,85)).join(' / '):'아직 확정한 내용이 없습니다. 그림을 보며 필요한 부분을 기록하세요.');
      }
      summary.append(title,brief);detail.append(summary);
      const table=node('table',undefined,'khtp-table'),tbody=node('tbody');
      for (const definition of definitions) {
        const id=definition.id,row=job.observations[id],tr=node('tr');tr.dataset.item=id;
        const th=node('th',definition.title);th.scope='row';const td=node('td');
        if(id==='O8.1') {
          td.append(node('p',row.text),node('p',row.reason));const refs=node('ul',undefined,'khtp-ref-list');
          const grouped=new Map();row.refs.forEach(ref=>{const values=grouped.get(ref.item)||new Set();values.add(ref.reason);grouped.set(ref.item,values);});
          for(const [item,reasons] of grouped)refs.append(node('li',`${job.pack.items.find(d=>d.id===item).title}: ${[...reasons].join(' / ')}`));td.append(refs);
        } else {
          const line=node('div',undefined,'khtp-state-line'),select=node('select');select.setAttribute('aria-label',`${definition.title} 상태`);
          for(const [key,label] of Object.entries(labels))select.append(new Option(label,key));select.value=row.state;
          const author=node('span',row.author==='user'?'직접 수정':'자동 초안', 'khtp-author');
          select.addEventListener('change',()=>{
            if(select.value==='absent' && row.author==='auto') {
              row.text='';text.value='';row.reason='관찰 가능한 범위에서 없음을 직접 확인했습니다.';reason.value=row.reason;
            }
            row.state=select.value;mark(id);author.textContent='직접 수정';if(selected===id)draw(id);
          });line.append(select,author);td.append(line);
          const text=node('textarea');text.value=row.text;text.maxLength=12000;text.setAttribute('aria-label',`${definition.title} 관찰 내용`);
          text.addEventListener('input',()=>{row.text=text.value;mark(id);author.textContent='직접 수정';});td.append(text);
          const reasonLabel=node('label','불확실한 이유·보충 메모','khtp-field-label'),reason=node('textarea',undefined,'khtp-reason');reason.value=row.reason;reason.maxLength=12000;
          reason.setAttribute('aria-label',`${definition.title} 이유`);reason.addEventListener('input',()=>{row.reason=reason.value;mark(id);author.textContent='직접 수정';});reasonLabel.append(reason);td.append(reasonLabel);
          if(!['O2.4'].includes(id)) td.append(regionEditor(id,row));
        }
        const reference=node('details');reference.append(node('summary','관찰 정의'),node('p',definition.definition),node('p','구별할 표현: '+definition.exclusions),node('p','불확실할 때: '+definition.uncertainty));td.append(reference);tr.append(th,td);tbody.append(tr);
      }
      table.append(tbody);detail.append(table);
      if(group.id==='O4'&&job.extras.length){const extra=node('button','잎·열매 참고 후보 보기','button small');extra.type='button';extra.addEventListener('click',()=>draw('extra'));detail.append(extra,node('p','참고 후보의 종류·단위는 확정하지 않았습니다.'));}
      groups.append(detail);
    }
    const sources=$('source-content');sources.replaceChildren(node('p',job.pack.notice));
    for(const source of job.pack.sources){const div=node('div',undefined,'khtp-source-row');
      if(source.url){const link=node('a',source.title);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';div.append(link);}else div.append(node('strong',source.title));
      div.append(node('p',source.location),node('p',source.note));sources.append(div);
    }
    sources.append(node('h3','단일 사진의 한계'));
    for(const item of job.pack.photo_limits)sources.append(node('p',`${item.title}: 이 입력으로 판단불가. ${item.reason}`));
    draw(selected);
  }
  async function action(kind) {
    if(busy||!job)return false;
    const captured={...dirty},capturedSubject={...subjectDirty};let payload;
    try {payload=requestBody();}catch(error){status(error.message);return false;}
    lock(true);
    status(kind==='analyze'?'그림의 후보 영역을 분석하고 있습니다. 잠시 기다려 주세요. 기다리는 동안에도 수정할 수 있으며 직접 수정한 내용은 유지됩니다.':kind==='pdf'?'현재 내용을 저장하고 PDF를 만들고 있습니다.':'현재 내용을 저장하고 있습니다.');
    try {
      const {response,data}=await request(`/khtp/${job.id}/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(data?.job)adopt(data.job,captured,capturedSubject);
      if(!response.ok)throw new Error(data?.message || '작업을 완료하지 못했습니다.');
      if(kind==='pdf') {
        job.revision=Number(response.headers.get('X-KHTP-Revision'));
        for(const id of Object.keys(captured))if(dirty[id]===captured[id])delete dirty[id];
        for(const key of Object.keys(capturedSubject))if(subjectDirty[key]===capturedSubject[key])delete subjectDirty[key];
        const blob=await response.blob(),url=URL.createObjectURL(blob),link=node('a');link.href=url;link.download='KHTP-observation.pdf';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
        try {
          const refreshed=await request(`/khtp/${job.id}/data`);
          if(refreshed.response.ok && refreshed.data.job?.id===job.id && refreshed.data.job.revision===job.revision) adopt(refreshed.data.job,captured,capturedSubject);
        } catch { /* The downloaded snapshot is saved; keep any ongoing edits. */ }
        const detached=Number(response.headers.get('X-KHTP-Detached-Schedules'));
        const notice=Number.isSafeInteger(detached)&&detached>0 ? ` 대상자가 달라진 일정 ${detached}건의 검사 연결을 해제했습니다. 일정의 대상자와 시간은 유지됩니다.` : '';
        status((isDirty()?'PDF 요청 당시 내용은 저장·출력했습니다. 대기 중 수정한 내용은 아직 저장하지 않았습니다.':'현재 내용으로 PDF를 받았습니다.')+notice);
      } else status(data.message+(isDirty()?' 대기 중 수정한 내용은 아직 저장하지 않았습니다.':''));
      return true;
    } catch(error){status(error.message,true);return false;}finally{lock(false);}
  }
  for(const key of subjectFields)$(key).addEventListener('input',()=>{
    subjectDirty[key]=++sequence;status('수정한 대상 정보가 있습니다. 분석하거나 저장해 주세요.');
  });
  $('person_id').addEventListener('input',()=>{
    subjectDirty.person_id=++sequence;status('대상자 연결을 변경했습니다. 저장하면 반영됩니다.');
  });
  $('file').addEventListener('change',()=>{
    const file=$('file').files[0];if(preview)URL.revokeObjectURL(preview);
    $('file-preview').hidden=!file;if(!file)return;preview=URL.createObjectURL(file);
    $('file-preview').querySelector('img').src=preview;$('filename').textContent=file.name;
  });
  $('start').addEventListener('click',async()=>{
    if(busy)return;const file=$('file').files[0];if(!file)return;
    let subject;try{subject=validateSubject();}catch(error){status(error.message);return;}
    const capturedSubject={...subjectDirty};const form=new FormData();form.append('image',file);
    for(const [key,value] of Object.entries(subject))form.append(key,value);
    form.append('person_id',$('person_id').value);
    lock(true);status('그림을 확인하고 있습니다.');
    try{const {response,data}=await request('/khtp/upload',{method:'POST',body:form});if(!response.ok)throw new Error(data.message);selected=null;adopt(data.job,{},capturedSubject);root.dataset.jobId=job.id;history.replaceState(null,'',data.job.url);$('file').value='';lock(false);await action('analyze');}
    catch(error){status(error.message,true);}finally{lock(false);}
  });
  $('save').addEventListener('click',()=>action('save'));
  $('analyze').addEventListener('click',()=>action('analyze'));
  $('pdf').addEventListener('click',()=>action('pdf'));
  $('pdf-bottom').addEventListener('click',()=>action('pdf'));
  $('expand').addEventListener('click',()=>{const all=[...document.querySelectorAll('.khtp-group')],open=all.some(v=>!v.open);all.forEach(v=>v.open=open);$('expand').textContent=open?'항목 접기':'전체 항목 보기';});
  $('zoom').addEventListener('click',()=>{$('canvas').classList.toggle('zoomed');$('zoom').textContent=$('canvas').classList.contains('zoomed')?'원래 크기':'확대 보기';});
  $('new').addEventListener('click',()=>{
    if(isDirty()&&!confirm('저장하지 않은 수정이 있습니다. 다른 그림을 선택하시겠습니까?'))return;
    job=null;dirty={};subjectDirty={};selected=null;
    window.HaeseokPeople?.set('khtp-person-picker',null);$('person_id').value='';
    syncShareLink();
    root.dataset.jobId='';history.replaceState(null,'','/khtp/new');
    for(const key of subjectFields)$(key).value=key==='exam_date'?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()):'';
    $('upload').hidden=false;$('work').hidden=true;$('pdf').hidden=true;$('sources').hidden=true;
    $('groups').replaceChildren();$('svg').replaceChildren();$('file').value='';$('file-preview').hidden=true;
    if(preview){URL.revokeObjectURL(preview);preview=null;}
    status('새 대상 정보와 그림을 입력해 주세요.');$('name').focus();
  });
  window.addEventListener('beforeunload',event=>{if(isDirty()){event.preventDefault();event.returnValue='';}});
  if(root.dataset.jobId) {
    lock(true);
    request(`/khtp/${root.dataset.jobId}/data`).then(({response,data})=>{if(!response.ok)throw new Error(data.message);adopt(data.job);status((job.analysis.status==='running'?'이전 분석이 끝나지 않았습니다. 다시 분석할 수 있습니다.':'저장한 검사 기록을 불러왔습니다.')+(isDirty()?' 불러오는 중 수정한 대상 정보는 아직 저장하지 않았습니다.':''));lock(false);}).catch(error=>status(error.message,true));
  } else status('그림을 선택하면 미리보기를 확인할 수 있습니다.');
})();
