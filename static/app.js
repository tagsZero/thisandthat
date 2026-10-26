document.querySelectorAll('[data-password-toggle]').forEach((button) => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    const showing = input.type === 'password';
    input.type = showing ? 'text' : 'password';
    button.textContent = showing ? '숨김' : '표시';
    button.setAttribute('aria-pressed', String(showing));
  });
});

document.querySelectorAll('.quick-review').forEach((detail) => {
  detail.addEventListener('toggle', () => {
    if (detail.open) {
      document.querySelectorAll('.quick-review').forEach((other) => {
        if (other !== detail) other.open = false;
      });
    }
  });
});

const scoreForm = document.querySelector('[data-preview-url]');
if (scoreForm) {
  const fields = scoreForm.elements;
  const output = document.getElementById('classification-preview');
  const status = document.getElementById('preview-status');
  let revision = 0;
  let timer;
  let controller;
  const isCalculationField = (name) => /_(raw|t|percentile|low|high|override)$/.test(name) ||
    ['preset', 'low', 'high', 'rounding'].includes(name);

  function refreshOverrides() {
    scoreForm.querySelectorAll('input[name$="_override"]').forEach((checkbox) => {
      const code = checkbox.name.split('_')[0];
      fields[`${code}_low`].disabled = !checkbox.checked;
      fields[`${code}_high`].disabled = !checkbox.checked;
    });
  }

  async function preview(currentRevision) {
    controller = new AbortController();
    try {
      const response = await fetch(scoreForm.dataset.previewUrl, {
        method: 'POST', body: new FormData(scoreForm), signal: controller.signal,
        headers: { Accept: 'application/json' },
      });
      if (currentRevision !== revision) return;
      if (response.redirected) throw new Error('session');
      const result = await response.json();
      if (currentRevision !== revision) return;
      output.style.minHeight = '';
      scoreForm.querySelectorAll('[data-error-for]').forEach((node) => {
        if (!isCalculationField(node.dataset.errorFor)) return;
        const message = result.errors?.[node.dataset.errorFor] || '';
        node.textContent = message;
        const input = fields[node.dataset.errorFor];
        if (input) {
          if (message) {
            input.setAttribute('aria-invalid', 'true');
            const detail = input.closest('details');
            if (detail) detail.open = true;
          }
          else input.removeAttribute('aria-invalid');
        }
      });
      if (response.status === 422) {
        scoreForm.querySelectorAll('[data-input-grade]').forEach(el => { el.textContent = '확인 필요'; });
        status.textContent = '입력 오류를 수정하면 미리보기를 표시합니다.';
        output.replaceChildren();
      } else if (response.ok && typeof result.html === 'string') {
        scoreForm.querySelectorAll('[data-input-grade]').forEach(el => { el.textContent = result.grades[el.dataset.inputGrade] || '미입력'; });
        output.innerHTML = result.html;
        status.textContent = '현재 입력 기준 · 아직 저장하지 않은 변경은 미리보기에만 반영됩니다.';
      } else throw new Error('preview');
    } catch (error) {
      if (error.name !== 'AbortError' && currentRevision === revision) {
        scoreForm.querySelectorAll('[data-input-grade]').forEach(el => { el.textContent = '확인 필요'; });
        output.style.minHeight = '';
        output.replaceChildren();
        status.textContent = '미리보기를 불러오지 못했습니다. 로그인 상태를 확인하고 갱신해 주세요.';
      }
    }
  }

  function schedulePreview() {
    revision += 1; // Invalidate old responses immediately, before the debounce expires.
    clearTimeout(timer);
    controller?.abort();
    output.style.minHeight = `${output.getBoundingClientRect().height}px`;
    output.replaceChildren();
    status.textContent = '분류를 계산하고 있습니다…';
    scoreForm.querySelectorAll('[data-input-grade]').forEach(el => { el.textContent = '계산 중'; });
    const currentRevision = revision;
    timer = setTimeout(() => preview(currentRevision), 250);
  }

  scoreForm.addEventListener('input', (event) => {
    if (!isCalculationField(event.target.name)) return;
    if (['low', 'high'].includes(event.target.name)) fields.preset.value = 'custom';
    if (event.target.name === 'preset' && fields.preset.value !== 'custom') {
      fields.low.value = '45';
      fields.high.value = fields.preset.value === 't55' ? '55' : '56';
    }
    if (fields.preset.value === 'custom') scoreForm.querySelector('.classification-settings').open = true;
    refreshOverrides();
    schedulePreview();
  });
  scoreForm.addEventListener('submit', (event) => {
    if (event.submitter?.name === 'preview_only') {
      event.preventDefault();
      schedulePreview();
    }
  });
  refreshOverrides();
}
