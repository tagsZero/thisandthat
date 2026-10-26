// 편집 상태를 덮어쓰지 않는 바이너리 다운로드. 오류 HTML/JSON은 파일로 저장하지 않는다.
window.tciPdf = {
  async receive(response, status) {
    const type = response.headers.get('Content-Type') || '';
    if (response.ok && type.split(';')[0].trim() === 'application/pdf') {
      const blob = await response.blob();
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const head = new TextDecoder().decode(bytes.slice(0, 5));
      const tail = new TextDecoder().decode(bytes.slice(-1024));
      if (head !== '%PDF-' || !tail.includes('%%EOF')) throw new Error('PDF 응답이 비어 있거나 손상됐습니다.');
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      try {
        link.href = url;
        link.download = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'TCI-report.pdf';
        document.body.append(link); link.click(); link.remove();
      } finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
      status.textContent = '제출한 내용은 저장됐으며 PDF를 다운로드했습니다.';
      return true;
    }
    if (type.includes('application/json')) {
      const result = await response.json();
      status.textContent = result.message || Object.values(result.errors || {}).join(' ') || 'PDF 요청에 실패했습니다.';
      if (result.save_state === 'saved' && result.retry_url) {
        status.append(document.createTextNode(' 다른 편집이 저장됐다면 현재 저장 내용을 출력합니다. '));
        const retry = document.createElement('a'); retry.href = result.retry_url;
        let retrying = false;
        retry.addEventListener('click', async event => {
          // 다운로드는 문서 이탈이 아니다. 공통 이동 guard를 해제하지 않는다.
          event.preventDefault();
          if (retrying) return;
          retrying = true; status.textContent = '저장된 보고서 PDF 생성 중…';
          try {
            const response = await fetch(retry.href, {headers:{Accept:'application/json'}});
            if (response.redirected) throw new Error('로그인 상태를 확인해 주세요.');
            if (await window.tciPdf.receive(response, status)) status.textContent = '저장된 보고서 PDF를 다운로드했습니다. 현재 미저장 설정은 유지됩니다.';
          } catch (error) {
            status.textContent = 'PDF 재시도 확인 실패 · 현재 입력은 유지됩니다. ' + error.message + ' ';
            status.append(retry);
          } finally { retrying = false; }
        });
        retry.textContent = '저장된 보고서 PDF만 재시도'; status.append(retry);
      }
      return false;
    }
    throw new Error('PDF 응답을 확인하지 못했습니다. 입력은 유지됩니다. 로그인·저장 상태를 확인해 주세요.');
  }
};
document.querySelectorAll('[data-pdf-form]').forEach(form => {
  let busy = false, revision = 0;
  form.addEventListener('input', () => revision++);
  form.addEventListener('submit', async event => {
    if (event.submitter?.value !== 'pdf') return;
    event.preventDefault(); if (busy) return; busy = true;
    const optionsPanel = form.closest?.('details');
    if (optionsPanel) optionsPanel.open = true;
    const submitted = revision, status = form.querySelector('[data-pdf-status]');
    const submittedOptions = Object.fromEntries(['subscales','combined','summary'].map(key => [key, Boolean(form.elements?.['include_' + key]?.checked)]));
    status.textContent = '저장 후 PDF 생성 중…';
    try {
      const response = await fetch(event.submitter.formAction, {method:'POST', body:new FormData(form), headers:{Accept:'application/json'}});
      if (response.headers?.get('X-TCI-Save-State') === 'saved' && typeof CustomEvent !== 'undefined') form.dispatchEvent(new CustomEvent('outputsaved', {detail:submittedOptions}));
      const completed = await window.tciPdf.receive(response, status);
      if (completed && revision === submitted) {
        const notice = document.querySelector('[data-output-preview]');
        if (notice) notice.textContent = '제출한 표시 설정을 저장하고 PDF를 다운로드했습니다.';
      }
      if (form.hasAttribute?.('data-saved-options') && response.headers?.get('X-TCI-Save-State') === 'saved') {
        status.append(document.createTextNode(' 아래 웹 본문은 마지막으로 연 미리보기입니다. 저장된 표시 설정은 보고서를 다시 열어 확인하세요.'));
      }
      if (revision !== submitted) status.append(document.createTextNode(' 이후 변경한 표시 설정은 미저장입니다.'));
    } catch (error) { status.textContent = 'PDF 다운로드 확인 실패 · 현재 입력은 유지됩니다. ' + error.message; }
    finally { busy = false; }
  });
});
