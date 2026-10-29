const scoreSaveForm = document.querySelector('[data-preview-url]');
if (scoreSaveForm) {
  const snapshot = () => JSON.stringify([...new FormData(scoreSaveForm)].filter(([key]) => !['_csrf', 'score_context'].includes(key)));
  let baseline = snapshot(), busy = false;
  const status = scoreSaveForm.querySelector('[data-score-save-status]');
  const navigation = window.tciNavigation.register({isDirty: () => snapshot() !== baseline, save: () => saveScores()});
  async function saveScores(destination) {
    if (busy) return false;
    busy = true;
    let submitted = snapshot();
    const data = new FormData(scoreSaveForm);
    data.set('destination', destination || 'stay');
    status.textContent = '저장 중…';
    try {
      const response = await fetch(location.pathname + location.search, {method:'POST', body:data, headers:{Accept:'application/json'}});
      if (response.redirected) throw new Error('로그인 상태를 확인해 주세요.');
      const result = await response.json();
      if (!response.ok) throw new Error(Object.values(result.errors || {}).join(' ') || '저장 실패');
      if (result.score_context) scoreSaveForm.elements.score_context.value = result.score_context;
      if (result.person && scoreSaveForm.elements.person_id.value === data.get('person_id')) {
        window.HaeseokPeople?.set('tci-person-picker', result.person);
        submitted = JSON.stringify(JSON.parse(submitted).map(([key,value]) => [key, key === 'person_id' ? String(result.person.id) : value]));
      }
      baseline = submitted;
      // 신규 건의 후속 저장도 동일한 검사 기록에 반영한다.
      if (result.edit_url && location.pathname.endsWith('/new')) history.replaceState(null, '', result.edit_url);
      status.textContent = submitted === snapshot() ? '검사 결과를 저장했습니다.' : '제출한 내용은 저장됐습니다. 이후 수정 내용은 미저장입니다.';
      if (result.notice) status.textContent += ' ' + result.notice;
      if (destination && submitted === snapshot()) navigation.leave(() => {
        if (result.draft_ticket) {
          const transfer = document.createElement('form'); transfer.method = 'post'; transfer.action = result.destination;
          for (const [name, value] of Object.entries({type_workspace:'1', action:'open_draft', draft_ticket:result.draft_ticket})) {
            const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; transfer.append(input);
          }
          document.body.append(transfer); transfer.submit();
        } else location.href = result.destination;
      });
      return submitted === snapshot();
    } catch (error) { status.textContent = '저장 확인 실패 · 입력을 유지했습니다. ' + error.message; return false; }
    finally { busy = false; }
  }
  scoreSaveForm.addEventListener('submit', event => {
    if (event.submitter?.name === 'preview_only') return;
    event.preventDefault(); saveScores(event.submitter?.value || 'candidates');
  });
}
