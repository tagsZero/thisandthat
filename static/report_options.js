const reportOptionsForm = document.querySelector('[data-saved-options]');
if (reportOptionsForm) {
  const keys = ['subscales','combined','summary'];
  const snapshot = () => Object.fromEntries(keys.map(key => [key, reportOptionsForm.elements['include_' + key].checked]));
  const fingerprint = options => JSON.stringify(keys.map(key => options[key]));
  let baseline = fingerprint(JSON.parse(reportOptionsForm.dataset.savedOptions));
  const dirty = () => fingerprint(snapshot()) !== baseline;
  const navigation = window.tciNavigation.register({isDirty:dirty, save:async () => {
    const response = await fetch(location.pathname, {method:'POST', body:new URLSearchParams({...Object.fromEntries(keys.filter(key => snapshot()[key]).map(key => ['include_'+key,'1'])),action:'save_output'}), headers:{Accept:'application/json'}});
    if (!response.ok || response.redirected) return false;
    const result = await response.json();
    if (result.save_state === 'saved') baseline = fingerprint(result.options);
    return !dirty();
  }});
  reportOptionsForm.addEventListener('outputsaved', event => { baseline = fingerprint(event.detail); });
  reportOptionsForm.addEventListener('submit', event => {
    if (event.submitter?.value === 'pdf') return;
    // 명시적인 표시·저장 제출은 현재 설정을 서버로 전달한다.
    navigation.leave(() => {});
  });
}
