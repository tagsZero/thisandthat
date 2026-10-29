(() => {
  'use strict';
  function element(value) {return typeof value === 'string' ? document.getElementById(value) : value;}
  function set(value, person) {
    const root=element(value);if(!root)return;
    const input=root.querySelector('[name=person_id]'),current=root.querySelector('[data-person-current]'),detail=root.querySelector('[data-person-detail]'),reset=root.querySelector('[data-person-reset]');
    input.value=person?.id || '';
    current.textContent=person ? `code:${String(person.code).padStart(4,'0')} · ${person.name || person.reference || '이름 미입력'}` : root.dataset.emptyLabel;
    detail.hidden=!person;reset.hidden=!person;
    if(person)detail.href=`/people/${encodeURIComponent(person.id)}`;else detail.removeAttribute('href');
    root.person=person || null;
  }
  for(const root of document.querySelectorAll('[data-person-picker]')) {
    const input=root.querySelector('[name=person_id]'),search=root.querySelector('[data-person-search]'),results=root.querySelector('[data-person-results]'),status=root.querySelector('[data-person-status]');
    root.dataset.emptyLabel=root.querySelector('[data-person-hint]').textContent.includes('처음 입력')?'새 대상자':'대상자 연결 없음';
    let timer,controller,serial=0;
    function clearResults(){clearTimeout(timer);controller?.abort();serial++;results.replaceChildren();results.hidden=true;status.textContent='';}
    function choose(person) {
      clearResults();set(root,person);search.value='';
      if(person)for(const [selector,key] of [[root.dataset.nameSelector,'name'],[root.dataset.referenceSelector,'reference']]) {
        if(!selector)continue;const field=document.querySelector(selector);if(!field)continue;
        field.value=person[key] || '';field.dispatchEvent(new Event('input',{bubbles:true}));
      }
      input.dispatchEvent(new Event('input',{bubbles:true}));
      root.dispatchEvent(new CustomEvent('personchange',{bubbles:true,detail:{person}}));
      status.textContent=person ? '선택한 대상자에 이번 기록을 연결합니다.' : '대상자 선택을 해제했습니다.';
    }
    root.querySelector('[data-person-reset]').addEventListener('click',()=>choose(null));
    search.addEventListener('input',()=>{
      clearResults();const query=search.value.trim();if(!query)return;
      const requestId=serial;
      timer=setTimeout(async()=>{
        controller=new AbortController();status.textContent='대상자를 찾고 있습니다.';
        try {
          const response=await fetch(`/people/search?q=${encodeURIComponent(query)}`,{signal:controller.signal,headers:{Accept:'application/json'}});
          if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))throw new Error();
          const data=await response.json();if(requestId!==serial)return;
          for(const person of data.items || []) {
            const li=document.createElement('li'),button=document.createElement('button'),title=document.createElement('span'),detail=document.createElement('small');button.type='button';
            title.textContent=`code:${String(person.code).padStart(4,'0')} · ${person.name || '이름 미입력'}`;
            detail.textContent=[person.reference || '관리번호 없음',person.registered_on || '등록일 없음'].join(' · ');
            button.append(title,detail);button.addEventListener('click',()=>choose(person));li.append(button);results.append(li);
          }
          results.hidden=!results.children.length;status.textContent=results.children.length?'연결할 대상자를 선택하세요.':'등록된 대상자가 없습니다.';
        } catch(error) {if(error.name!=='AbortError' && requestId===serial)status.textContent='검색하지 못했습니다. 로그인 상태를 확인하고 다시 입력해 주세요.';}
      },180);
    });
    search.addEventListener('keydown',event=>{
      // Search input is not a save action. Results stay selectable with Tab/Enter.
      if(event.key==='Enter'){event.preventDefault();return;}
      if(event.key==='Escape'){clearResults();search.value='';}
    });
  }
  window.HaeseokPeople={set};
})();
