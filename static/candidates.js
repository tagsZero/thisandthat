const candidateForm = document.querySelector('[data-candidate-form]');
if (candidateForm) {
  const fields = candidateForm.elements, output = document.getElementById('candidate-results');
  const status = document.getElementById('candidate-status'), saveStatus = document.getElementById('save-status');
  const editor = document.getElementById('composition-editor'), hidden = document.getElementById('composition-data');
  const labels = JSON.parse(document.getElementById('composition-labels').textContent);
  const selectionLabels = JSON.parse(document.getElementById('selection-labels')?.textContent || '{}');
  const topicLabel = key => selectionLabels.topics?.[key] || key;
  const relationLabel = key => selectionLabels.relations?.[key] || key;
  const sectionOrder = [...editor.querySelectorAll('[data-section]')].map(el => el.dataset.section);
  let state = JSON.parse(hidden.value), flags = JSON.parse(document.getElementById('block-status-data').textContent);
  const groupID = selection => selection ? selection.topic + '/' + selection.group : null;
  const allBlocks = () => Object.values(state.sections).flatMap(s => s.blocks);
  function pruneModes() {
    if (!state.group_modes) return;
    const groups = new Set(allBlocks().map(b => groupID(b.selection)).filter(Boolean));
    state.group_modes = Object.fromEntries(Object.entries(state.group_modes).filter(([key]) => groups.has(key)));
  }
  const initialContext = JSON.parse(document.getElementById('composition-current-context').textContent);
  let currentSettings = initialContext.settings, currentScores = initialContext.scores;
  const profile = document.getElementById('workspace-profile'), validSettings = document.getElementById('valid-settings');
  let lookupValid = initialContext.valid !== false;
  let revision = 0, changes = 0, timer, controller, saving = false;
  let savedChanges = 0, savePromise;
  const navigation = globalThis.tciNavigation?.register({
    isDirty: () => changes !== savedChanges,
    save: async () => {
      candidateForm.requestSubmit(candidateForm.querySelector('button[value="save"]'));
      if (savePromise) await savePromise;
      return changes === savedChanges;
    }
  });
  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  }
  function sync() {
    hidden.value = JSON.stringify(state);
    candidateForm.querySelectorAll('[data-selection-count]').forEach(el => {
      el.textContent = Object.values(state.sections).reduce((sum, section) => sum + section.blocks.length, 0);
    });
  }
  function dirty() { changes++; sync(); saveStatus.textContent = '미저장 · 현재 작성 내용을 저장해 주세요.'; }
  function flagText(block) {
    const f = flags[block.id] || {};
    return [f.reference ? '추가 참고' : '', f.previous ? '이전 기준에서 선택' : '', f.mismatch ? '현재 적용 조건과 다름' : '', f.changed ? '자료 변경 또는 사용 불가' : ''].filter(Boolean).join(' · ');
  }
  function markSelections() {
    output.querySelectorAll('[data-offer]').forEach(button => {
      const offer = JSON.parse(button.dataset.offer);
      const selected = allBlocks().some(b => b.item_ids.some(id => offer.item_ids.includes(id)) || b.evidence.description.trim().replace(/\s+/g, ' ') === offer.evidence.description.trim().replace(/\s+/g, ' '));
      button.setAttribute('aria-pressed', String(selected)); button.textContent = selected ? '선택됨 · 해제' : '선택';
    });
  }
  function updateFlags() {
    editor.querySelectorAll('[data-block]').forEach(article => {
      const block = Object.values(state.sections).flatMap(s => s.blocks).find(b => b.id === article.dataset.block);
      if (block) article.querySelector('.block-flags').textContent = flagText(block);
      const current = article.querySelector('[data-current-settings]');
      if (current) current.textContent = '현재 기준: ' + JSON.stringify(currentSettings);
      const scores = article.querySelector('[data-current-scores]');
      if (scores) scores.textContent = '현재 점수: ' + JSON.stringify(currentScores);
    });
  }
  function renderEditor() {
    const open = new Set([...editor.querySelectorAll('[data-section][open]')].map(d => d.dataset.section));
    editor.replaceChildren(node('h2', '선택문 편집·미리보기'), node('p', '선택한 문장과 직접 의견만 반영됩니다. 저장 버튼으로 현재 기준과 함께 저장하세요.', 'settings-note'));
    const groups = new Map(allBlocks().filter(b => b.selection).map(b => [groupID(b.selection), b.selection]));
    for (const [group, selection] of groups) {
      const label = node('label', `${topicLabel(selection.topic)} · 선택 묶음 ${selection.group}`), mode = node('select'); mode.name = 'group_mode_' + group;
      for (const [value, text] of [['multiple','여러 개 선택'],['single','하나 선택']]) {
        const option = node('option', text); option.value = value; option.selected = value === (state.group_modes?.[group] || 'multiple'); mode.append(option);
      }
      label.append(mode); editor.append(label);
    }
    for (const key of sectionOrder) {
      const section = state.sections[key];
      const detail = node('details', undefined, 'composition-section'); detail.dataset.section = key;
      detail.open = open.has(key) || section.blocks.length > 0 || Boolean(section.opinion);
      detail.append(node('summary', `${labels[key]} · ${section.blocks.length}개`));
      for (const block of section.blocks) {
        const article = node('article', undefined, 'selected-block'); article.dataset.block = block.id;
        article.append(node('p', flagText(block), 'block-flags'));
        article.append(node('p', block.selection ? `${topicLabel(block.selection.topic)} · 선택 묶음 ${block.selection.group} · 대표 관계 ${relationLabel(block.selection.relation)}` : '선택 묶음 미확인 · 자동 교체 대상 제외', 'settings-note'));
        const positionLabel = node('label', '보고서 반영 위치'), position = node('select'); position.name = 'position_' + block.id;
        for (const target of sectionOrder) {
          const option = node('option', labels[target]); option.value = target; option.selected = target === key; position.append(option);
        }
        positionLabel.append(position); article.append(positionLabel);
        const label = node('label', '선택문 편집'), text = node('textarea'); text.rows = 4; text.name = 'text_' + block.id; text.value = block.text;
        label.append(text); article.append(label);
        const actions = node('div', undefined, 'block-actions');
        for (const [action, title] of [['up','위로'],['down','아래로'],['remove','제외']]) {
          const button = node('button', title); button.type = 'submit'; button.name = 'action'; button.value = `${action}:${block.id}`; actions.append(button);
        }
        article.append(actions);
        const evidence = node('details', undefined, 'block-evidence'); evidence.append(node('summary', '선택 당시 문장·출처·기준 보기'), node('p', block.evidence.description));
        for (const m of block.evidence.members) {
          evidence.append(node('p', `출처: ${m.source.title} · ${m.item.location} · 항목 #${m.item.id} · 검사판 ${m.item.edition} / ${m.source.edition}`), node('p', `파일: ${m.source.filename} / ${m.source.alternate_filename} · 적용 범위: ${m.item.scope} / ${m.source.scope}`), node('p', [...m.reasons, m.item.conflict].filter(Boolean).join(' · ')), node('p', '원문: ' + m.item.original), node('p', '조건: ' + JSON.stringify(m.item.conditions) + ' · 원래 기준 ' + m.item.original_criteria));
          if (m.item.selection) evidence.append(node('p', '설명 관계: ' + relationLabel(m.item.selection.relation)),
            node('p', '연결 근거: ' + m.item.selection.basis));
        }
        const current = node('p', '현재 기준: ' + JSON.stringify(currentSettings)); current.dataset.currentSettings = '';
        const scores = node('p', '현재 점수: ' + JSON.stringify(currentScores)); scores.dataset.currentScores = '';
        evidence.append(node('p', '선택 당시 기준: ' + JSON.stringify(block.evidence.settings)), node('p', '선택 당시 점수: ' + JSON.stringify(block.evidence.scores)), current, scores);
        const preview = node('p', block.text, 'selected-preview'); preview.hidden = true;
        article.append(evidence, preview); detail.append(article);
      }
      const label = node('label', '직접 의견'), opinion = node('textarea'); opinion.rows = 3; opinion.name = 'opinion_' + key; opinion.value = section.opinion;
      const preview = node('p', section.opinion, 'opinion-preview'); preview.hidden = true;
      label.append(opinion); detail.append(label, preview); editor.append(detail);
    }
    sync(); markSelections();
  }
  function refreshOverrides() {
    candidateForm.querySelectorAll('[name$="_override"]').forEach(checkbox => {
      const code = checkbox.name.split('_')[0]; fields[`${code}_low`].disabled = !checkbox.checked; fields[`${code}_high`].disabled = !checkbox.checked;
    });
  }
  function replaceResults(target, html) {
    if (!target || html === undefined) return;
    const opened = [...target.querySelectorAll('details')].map((el, index) => ({id:el.id, index, open:el.open}));
    target.innerHTML = html;
    const details = [...target.querySelectorAll('details')];
    opened.forEach(item => { const el = item.id ? details.find(el => el.id === item.id) : details[item.index]; if (el) el.open = item.open; });
  }
  function applyResults(result) {
    replaceResults(output, result.html);
    if (typeof Event !== 'undefined') output.dispatchEvent(new Event('topicsupdated'));
    replaceResults(profile, result.profile_html);
    flags = {...flags, ...result.block_status}; currentSettings = result.settings; currentScores = result.scores;
    if (validSettings) validSettings.value = JSON.stringify(currentSettings);
    lookupValid = true; output.inert = false;
    status.textContent = '현재 기준으로 조회했습니다. 비교와 새로고침은 저장하지 않습니다.';
    updateFlags(); markSelections();
  }
  async function refresh(currentRevision) {
    controller = new AbortController(); sync(); const data = new FormData(candidateForm); data.set('action', 'compare');
    data.set('_request_id', String(currentRevision));
    try {
      const response = await fetch(location.pathname, {method:'POST', body:data, headers:{Accept:'application/json'}, signal:controller.signal});
      if (currentRevision !== revision) return;
      if (response.redirected) throw new Error('로그인 상태를 확인해 주세요.');
      const result = await response.json(); if (currentRevision !== revision) return;
      if (result.request_id != null && result.request_id !== String(currentRevision)) throw new Error('조회 응답 기준을 확인하지 못했습니다.');
      candidateForm.querySelectorAll('[data-error-for]').forEach(el => { el.textContent = result.errors?.[el.dataset.errorFor] || ''; });
      if (!response.ok) throw new Error(Object.values(result.errors || {}).join(' '));
      applyResults(result); status.textContent = '현재 기준으로 조회했습니다. 비교와 새로고침은 저장하지 않습니다.';
    } catch (error) {
      if (error.name !== 'AbortError' && currentRevision === revision) {
        lookupValid = false; output.inert = true;
        status.textContent = '입력 기준과 표시 결과가 다를 수 있습니다. 마지막 유효 결과와 작성 내용을 유지했습니다. 다시 조회하세요. ' + error.message;
      }
    }
  }
  function schedule(delay) {
    revision++; clearTimeout(timer); controller?.abort(); output.inert = true;
    status.textContent = '현재 입력으로 조회 중… 표시된 프로파일·후보는 마지막 유효 결과입니다.';
    const currentRevision = revision; timer = setTimeout(() => refresh(currentRevision), delay);
  }
  candidateForm.addEventListener('input', event => {
    const name = event.target.name || '';
    if (!name) return; // 검토 주제 선택은 화면 위치이며 조회·작성 변경을 발생시키지 않는다.
    if (name.startsWith('group_mode_')) { state.group_modes[name.slice(11)] = event.target.value; dirty(); return; }
    if (name.startsWith('position_')) {
      const id = name.slice(9), block = allBlocks().find(b => b.id === id);
      if (!state.sections[event.target.value] || !block) return;
      for (const section of Object.values(state.sections)) section.blocks = section.blocks.filter(b => b.id !== id);
      state.sections[event.target.value].blocks.push(block); dirty(); renderEditor(); return;
    }
    if (name.startsWith('text_')) {
      const block = Object.values(state.sections).flatMap(s => s.blocks).find(b => b.id === name.slice(5)); block.text = event.target.value;
      event.target.closest('article').querySelector('.selected-preview').textContent = block.text; dirty(); return;
    }
    if (name.startsWith('opinion_')) { state.sections[name.slice(8)].opinion = event.target.value; event.target.closest('[data-section]').querySelector('.opinion-preview').textContent = event.target.value; dirty(); return; }
    if (name.startsWith('mode_')) { state.sections[name.slice(5)].mode = event.target.value; dirty(); return; }
    if (name.startsWith('include_')) {
      state.output = Object.fromEntries(['subscales','combined','summary'].map(key => [key, fields['include_' + key].checked]));
      dirty(); return;
    }
    if (['low','high'].includes(name)) fields.preset.value = 'custom';
    if (name === 'preset' && fields.preset.value !== 'custom') { fields.low.value = '45'; fields.high.value = fields.preset.value === 't55' ? '55' : '56'; }
    refreshOverrides(); dirty(); schedule(250);
  });
  candidateForm.addEventListener('submit', async event => {
    event.preventDefault(); const button = event.submitter, action = button?.value || 'compare';
    if (button?.dataset.offer) {
      if (output.inert) return;
      const block = JSON.parse(button.dataset.offer); block.id = 'b-' + crypto.randomUUID().replaceAll('-', '');
      const section = state.sections[block.evidence.section], overlap = allBlocks().filter(b => b.item_ids.some(id => block.item_ids.includes(id)) || b.evidence.description.trim().replace(/\s+/g, ' ') === block.evidence.description.trim().replace(/\s+/g, ' '));
      if (overlap.length) {
        for (const s of Object.values(state.sections)) s.blocks = s.blocks.filter(b => !overlap.includes(b));
      } else {
        const group = groupID(block.selection);
        if (group && state.group_modes?.[group] === 'single') {
          for (const s of Object.values(state.sections)) s.blocks = s.blocks.filter(b => groupID(b.selection) !== group);
        }
        section.blocks.push(block); flags[block.id] = {reference:block.evidence.members.some(m => m.category === 'reference')};
      }
      pruneModes(); dirty(); renderEditor(); return;
    }
    if (/^(up|down|remove):/.test(action)) {
      const [operation, id] = action.split(':');
      for (const section of Object.values(state.sections)) {
        const index = section.blocks.findIndex(b => b.id === id); if (index < 0) continue;
        if (operation === 'remove') section.blocks.splice(index, 1);
        else { const other = index + (operation === 'up' ? -1 : 1); if (other >= 0 && other < section.blocks.length) [section.blocks[index], section.blocks[other]] = [section.blocks[other], section.blocks[index]]; }
      }
      pruneModes(); dirty(); renderEditor(); return;
    }
    if (action === 'compare') { schedule(0); return; }
    if (!lookupValid) {
      saveStatus.textContent = '현재 입력 기준의 조회가 성공하지 않았습니다. 오류를 수정하고 비교를 갱신한 뒤 저장하세요.';
      return;
    }
    if (saving) return;
    let finishSave;
    savePromise = new Promise(resolve => { finishSave = resolve; });
    saving = true; revision++; clearTimeout(timer); controller?.abort(); sync();
    const submittedChanges = changes, submittedRevision = revision, data = new FormData(candidateForm); data.set('action', action); saveStatus.textContent = '저장 중…';
    try {
      const response = await fetch(location.pathname, {method:'POST', body:data, headers:{Accept:'application/json'}});
      if (action === 'pdf') {
        try { await window.tciPdf.receive(response, saveStatus); }
        finally {
          // 생성 실패·손상 응답이어도 저장이 확인됐다면 비교 기준선을 다시 읽는다.
          if (profile && response.headers?.get('X-TCI-Save-State') === 'saved') schedule(0);
        }
        if (changes !== submittedChanges) saveStatus.append(document.createTextNode(' 이후 수정 내용은 미저장입니다.'));
        return;
      }
      if (response.redirected) throw new Error('로그인 상태를 확인해 주세요.');
      const result = await response.json();
      if (result.save_state === 'saved') savedChanges = submittedChanges;
      if (result.save_state === 'saved' && !response.ok) {
        saveStatus.textContent = result.message + (changes !== submittedChanges ? ' 이후 수정 내용은 미저장입니다.' : '');
        if (profile) { lookupValid = false; output.inert = true; status.textContent = '저장 후 조회에 실패했습니다. 마지막 유효 결과입니다. 비교를 갱신하세요.'; }
        return;
      }
      if (!response.ok || Object.keys(result.errors || {}).length) throw new Error(Object.values(result.errors || {}).join(' ') || '서버 응답을 확인해 주세요.');
      if (revision !== submittedRevision) {
        saveStatus.textContent = '제출한 내용은 저장됐습니다. 이후 수정 내용은 미저장입니다.';
        schedule(0); return;
      }
      applyResults(result);
      if (changes !== submittedChanges) { saveStatus.textContent = '제출한 내용은 저장됐습니다. 이후 수정 내용은 미저장입니다.'; return; }
      saveStatus.textContent = result.message;
      if (result.destination) {
        if (navigation) navigation.leave(() => { location.href = result.destination; });
        else location.href = result.destination;
      }
    } catch (error) { saveStatus.textContent = '저장 확인 실패 · 현재 입력은 유지됩니다. 다시 저장해 주세요. ' + error.message; }
    finally {
      saving = false;
      finishSave();
      if (output.inert && revision === submittedRevision) {
        lookupValid = false;
        status.textContent = '표시된 프로파일·후보는 마지막 유효 결과입니다. 현재 입력 기준으로 비교를 다시 갱신하세요.';
      }
    }
  });
  output.addEventListener('click', event => {
    const ref = event.target.closest('a[href="#additional-references"]'); if (ref) document.getElementById('additional-references').open = true;
    const link = event.target.closest('[data-candidate-peer]'), target = link && document.getElementById(link.hash.slice(1));
    for (let parent = target?.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
  });
  refreshOverrides(); markSelections(); sync(); output.inert = !lookupValid;
}
