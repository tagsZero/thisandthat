// TYPE-03: 본문은 하나의 상태. 분류는 서버에서, 추가/취소/편집은 즉시 반영한다.
const typeForm = document.querySelector('[data-type-form]');
if (typeForm) {
  const fields = typeForm.elements, editor = document.getElementById('composition-editor');
  const hidden = document.getElementById('composition-data'), profile = document.getElementById('workspace-profile');
  const status = document.getElementById('candidate-status'), saved = document.getElementById('save-status');
  const initial = JSON.parse(document.getElementById('type-initial').textContent);
  let state = JSON.parse(hidden.value), valid = initial.valid, changes = initial.fresh ? 1 : 0, savedChanges = 0;
  let revision = 0, timer, controller, saving = false, pending = false;
  const blocks = () => Object.values(state.sections).flatMap(section => section.blocks);
  function savedTime(stamp) {
    if (!stamp) return;
    const time = document.querySelector('#last-saved time');
    const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(stamp) ? stamp : stamp + 'Z');
    time.dateTime = date.toISOString();
    time.textContent = date.toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}) + ' (한국 시간)';
  }
  savedTime(document.querySelector('#last-saved time').dateTime);
  function fitBodies() {
    editor.querySelectorAll('[data-block] textarea').forEach(el => {
      el.style.height = Math.max(180, el.scrollHeight + 2) + 'px';
    });
  }
  const node = (tag, text, className) => {
    const el = document.createElement(tag); if (text !== undefined) el.textContent = text;
    if (className) el.className = className; return el;
  };
  const navigation = window.tciNavigation.register({isDirty:() => changes !== savedChanges, save:() => send('save')});
  function sync() {
    editor.querySelectorAll('textarea').forEach(el => {
      if (el.name.startsWith('text_')) {
        const block = blocks().find(b => b.id === el.name.slice(5)); if (block) block.text = el.value;
      } else if (el.name.startsWith('opinion_')) state.sections[el.name.slice(8)].opinion = el.value;
    });
    hidden.value = JSON.stringify(state);
  }
  function dirty() { changes++; sync(); saved.textContent = '미저장 · 현재 작성 내용을 저장해 주세요.'; }
  function markAdditions() {
    editor.querySelectorAll('[data-offer]').forEach(button => {
      const offer = JSON.parse(button.dataset.offer);
      const selected = blocks().some(b => b.item_ids.some(id => offer.item_ids.includes(id)));
      const duplicate = !selected && blocks().some(b => b.evidence.description.replace(/\s+/g,' ').trim() === offer.evidence.description.replace(/\s+/g,' ').trim());
      button.setAttribute('aria-pressed', String(selected));
      button.textContent = selected ? '추가됨 · 취소' : duplicate ? '동일 설명이 본문에 포함되어 있습니다' : button.dataset.addLabel;
      // 추가된 문장의 취소는 느린 조회 중에도 허용한다.
      button.disabled = duplicate || (!selected && !valid);
    });
  }
  function prune() {
    const groups = new Set(blocks().filter(b => b.selection).map(b => b.selection.topic + '/' + b.selection.group));
    state.group_modes = Object.fromEntries(Object.entries(state.group_modes).filter(([key]) => groups.has(key)));
  }
  function remove(id) {
    for (const section of Object.values(state.sections)) section.blocks = section.blocks.filter(b => b.id !== id);
    editor.querySelector(`[data-block="${id}"]`)?.remove();
    prune(); dirty(); markAdditions();
  }
  function appendBlock(block, button) {
    const article = node('article', undefined, 'selected-block type-block'); article.dataset.block = block.id;
    article.append(node('p', block.evidence.members.some(m => m.category === 'reference') ? '추가 참고 · 적용 조건 확인 필요' : '', 'block-flags'));
    const label = node('label', '추가한 설명 · 직접 편집'), text = node('textarea');
    text.rows = 5; text.name = 'text_' + block.id; text.value = block.text; label.append(text); article.append(label);
    const actions = node('div', undefined, 'block-actions'), cancel = node('button', '추가 취소');
    cancel.type = 'button'; cancel.dataset.remove = block.id; actions.append(cancel);
    for (const [direction, title] of [['up','위로'],['down','아래로']]) {
      const move = node('button', title); move.type = 'button'; move.dataset.move = direction; move.dataset.id = block.id; actions.append(move);
    }
    article.append(actions);
    const evidence = button.closest('[data-addition]').querySelector('details').cloneNode(true);
    evidence.dataset.detail = block.id; evidence.open = false; article.append(evidence);
    editor.querySelector(`[data-block-list="${block.evidence.section}"]`).append(article);
    text.style.height = Math.max(180, text.scrollHeight + 2) + 'px';
  }
  editor.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    sync();
    if (button.dataset.remove) { remove(button.dataset.remove); return; }
    if (button.dataset.move) {
      for (const [key, section] of Object.entries(state.sections)) {
        const index = section.blocks.findIndex(b => b.id === button.dataset.id); if (index < 0) continue;
        const other = index + (button.dataset.move === 'up' ? -1 : 1);
        if (other < 0 || other >= section.blocks.length) return;
        [section.blocks[index], section.blocks[other]] = [section.blocks[other], section.blocks[index]];
        const list = editor.querySelector(`[data-block-list="${key}"]`);
        section.blocks.forEach(b => list.append(editor.querySelector(`[data-block="${b.id}"]`)));
        dirty(); return;
      }
    }
    if (!button.dataset.offer || button.disabled) return;
    const offer = JSON.parse(button.dataset.offer);
    const selected = blocks().filter(b => b.item_ids.some(id => offer.item_ids.includes(id)));
    if (selected.length) { selected.forEach(b => remove(b.id)); return; }
    if (!valid) return;
    // 기본 본문과 다른 추가문을 교체하지 않는다. 동일 원문의 재추가는 한 개만 둔다.
    if (blocks().some(b => b.evidence.description.replace(/\s+/g,' ').trim() === offer.evidence.description.replace(/\s+/g,' ').trim())) return;
    offer.id = 'b-' + crypto.randomUUID().replaceAll('-', '');
    state.sections[offer.evidence.section].blocks.push(offer);
    if (offer.selection) delete state.group_modes[offer.selection.topic + '/' + offer.selection.group];
    appendBlock(offer, button); dirty(); markAdditions();
  });
  function preservePosition() {
    const active = document.activeElement;
    const item = active?.name ? {name:active.name, start:active.selectionStart, end:active.selectionEnd,
      direction:active.selectionDirection, scroll:active.scrollTop, top:active.getBoundingClientRect().top} : null;
    const scroll = window.scrollY;
    const opened = [...editor.querySelectorAll('details[open]')].map(el => el.dataset.detail);
    return () => {
      editor.querySelectorAll('details').forEach(el => { if (opened.includes(el.dataset.detail)) el.open = true; });
      const target = active?.isConnected ? active : item && fields.namedItem(item.name);
      if (item && target?.focus) {
        target.focus({preventScroll:true});
        if (item.start != null && target.setSelectionRange) target.setSelectionRange(item.start, item.end, item.direction);
        target.scrollTop = item.scroll;
        window.scrollBy(0, target.getBoundingClientRect().top - item.top);
      } else window.scrollTo(0, scroll);
    };
  }
  function apply(result) {
    const restore = preservePosition();
    state = result.composition; hidden.value = JSON.stringify(state);
    fields.type_context.value = result.type_context;
    editor.innerHTML = result.body_html; profile.innerHTML = result.profile_html;
    fitBodies();
    valid = true; pending = false; markAdditions(); restore();
    status.textContent = '현재 기준으로 유형과 수정하지 않은 자동 본문을 갱신했습니다.';
  }
  function refreshOverrides() {
    typeForm.querySelectorAll('[name$="_override"]').forEach(el => {
      const scale = el.name.split('_')[0]; fields[scale + '_low'].disabled = fields[scale + '_high'].disabled = !el.checked;
    });
  }
  function schedule(delay=250) {
    revision++; clearTimeout(timer); controller?.abort(); valid = false; pending = true; markAdditions();
    status.textContent = '기준 확인 중… 프로파일은 마지막 유효 결과입니다. 본문 편집은 유지됩니다.';
    timer = setTimeout(() => send('compare'), delay);
  }
  async function send(action) {
    if (saving) return false;
    if (action !== 'compare' && (pending || !valid)) {
      saved.textContent = '입력 기준 확인이 필요합니다. 기준 적용 · 다시 시도 후 저장해 주세요.'; return false;
    }
    const isSave = action !== 'compare';
    if (isSave) { saving = true; clearTimeout(timer); controller?.abort(); }
    sync();
    const sentRevision = ++revision, sentChanges = changes, data = new FormData(typeForm);
    data.set('action', action); data.set('_request_id', String(sentRevision));
    controller = new AbortController();
    if (isSave) saved.textContent = '저장 중…';
    // 이전 저장 기준선과 별개로 이번 요청에서 확인한 저장 결과만 사용한다.
    let requestSaveState = 'unconfirmed';
    const saveFailureMessage = () => requestSaveState === 'saved'
      ? (action === 'pdf' ? '제출한 내용은 저장됐지만 PDF 다운로드 확인에 실패했습니다.' : '제출한 내용은 저장됐지만 조회에 실패했습니다.')
      : ['failed', 'not_saved'].includes(requestSaveState)
        ? '이번 요청은 저장하지 못했습니다. 입력을 유지했습니다.'
        : '저장 확인 실패 · 입력을 유지했습니다.';
    try {
      const response = await fetch(typeForm.getAttribute('action'), {method:'POST', body:data, headers:{Accept:'application/json'},
        ...(isSave ? {} : {signal:controller.signal})});
      if (response.redirected) throw new Error('로그인 상태를 확인해 주세요.');
      if (action === 'pdf') {
        if (response.headers.get('X-TCI-Request-Id') !== String(sentRevision)) {
          // 저장 전 오류의 요청 식별자는 JSON 본문에서 확인한다.
          if (response.headers.get('X-TCI-Save-State') === 'saved') throw new Error('PDF 응답의 저장 확인을 읽을 수 없습니다.');
        }
        if (response.headers.get('X-TCI-Save-State') === 'saved'
            && response.headers.get('X-TCI-Request-Id') === String(sentRevision)) {
          requestSaveState = 'saved';
          fields.type_context.value = response.headers.get('X-TCI-Type-Context');
          savedChanges = sentChanges;
          savedTime(response.headers.get('X-TCI-Saved-At'));
        }
        if (response.ok && response.headers.get('Content-Type')?.includes('application/pdf')) {
          await window.tciPdf.receive(response, saved);
          if (changes !== sentChanges) saved.append(document.createTextNode(' 이후 수정 내용은 미저장입니다.'));
          if (pending) saved.append(document.createTextNode(' 변경한 기준은 확인 중입니다.'));
          return changes === savedChanges;
        }
        const result = await response.json();
        if (result.save_state !== 'saved' && result.request_id !== String(sentRevision)) throw new Error('응답 기준을 확인할 수 없습니다.');
        saved.textContent = result.save_state === 'saved'
          ? '제출한 내용은 저장됐지만 PDF 생성에 실패했습니다. 현재 내용을 저장 후 PDF 다운로드로 다시 시도하세요.'
          : '저장하지 못해 PDF를 생성하지 않았습니다. 입력을 유지했습니다. ' + Object.values(result.errors || {}).join(' ');
        if (changes !== sentChanges) saved.append(document.createTextNode(' 이후 수정 내용은 미저장입니다.'));
        return false;
      }
      const result = await response.json();
      if (result.request_id !== String(sentRevision)) throw new Error('응답 기준을 확인할 수 없습니다.');
      if (isSave && ['saved', 'failed', 'not_saved'].includes(result.save_state)) requestSaveState = result.save_state;
      if (isSave && result.save_state === 'saved') {
        savedChanges = sentChanges;
        // 저장 중 추가 편집은 유지하되 새 저장 기준의 서명만 받는다.
        if (result.type_context) fields.type_context.value = result.type_context;
        savedTime(result.saved_at);
      }
      if (sentRevision !== revision) {
        if (isSave) saved.textContent = requestSaveState === 'saved'
          ? '제출한 내용은 저장됐습니다. 이후 수정 내용은 미저장입니다.'
          : saveFailureMessage() + ' 이후 수정 내용은 미저장입니다.';
        return false;
      }
      typeForm.querySelectorAll('[data-error-for]').forEach(el => el.textContent = result.errors?.[el.dataset.errorFor] || '');
      if (!response.ok) throw new Error(Object.values(result.errors || {}).join(' ') || '서버 응답 오류');
      if (changes !== sentChanges) {
        if (isSave) saved.textContent = '제출한 내용은 저장됐습니다. 이후 수정 내용은 미저장입니다.';
        // 오래된 응답의 자동 본문도 적용하지 않고 최신 편집/삭제를 함께 재검증한다.
        schedule(0); return false;
      }
      apply(result);
      if (isSave) {
        saved.textContent = '현재 해석·기준을 저장했습니다.';
        if (result.destination) navigation.leave(() => { location.href = result.destination; });
      }
      return !isSave || changes === savedChanges;
    } catch (error) {
      if (error.name !== 'AbortError' && sentRevision === revision) {
        valid = false; pending = false; markAdditions();
        status.textContent = '마지막 유효 결과와 최신 편집문을 유지했습니다. 기준 적용 · 다시 시도로 재시도하세요. ' + error.message;
        if (isSave) saved.textContent = saveFailureMessage();
      }
      return false;
    } finally {
      if (isSave) {
        saving = false;
        if (pending) { clearTimeout(timer); timer = setTimeout(() => send('compare'), 0); }
      }
    }
  }
  typeForm.addEventListener('input', event => {
    const name = event.target.name || ''; if (!name) return;
    dirty();
    if (name.startsWith('text_') || name.startsWith('opinion_')) return;
    if (['low','high'].includes(name)) fields.preset.value = 'custom';
    if (name === 'preset' && fields.preset.value !== 'custom') { fields.low.value = '45'; fields.high.value = fields.preset.value === 't55' ? '55' : '56'; }
    refreshOverrides(); schedule();
  });
  typeForm.addEventListener('submit', event => {
    event.preventDefault();
    const action = event.submitter?.value || 'compare';
    if (action === 'compare') schedule(0); else send(action);
  });
  profile.addEventListener('click', event => {
    const key = event.target.closest('[data-open-topic]')?.dataset.openTopic;
    if (key) document.getElementById('type-' + (key.startsWith('temperament') ? 'temperament' : key.startsWith('character') ? 'character' : 'details'))?.scrollIntoView({block:'start'});
  });
  const focus = new URLSearchParams(location.search).get('focus');
  const target = focus && (fields.namedItem('text_' + focus) || fields.namedItem(focus));
  if (target) { target.closest('details')?.setAttribute('open',''); target.focus(); target.scrollIntoView({block:'center'}); }
  refreshOverrides(); fitBodies(); sync(); markAdditions();
}
