/* 자료 조건의 추가·삭제와 척도별 점수 선택만 담당한다. 검증 계약은 서버에 있다. */
(() => {
  const container = document.getElementById('numeric-rules');
  if (!container) return;
  const allowed = JSON.parse(document.getElementById('allowed-metrics').textContent);
  function update(row) {
    const scale = row.querySelector('[name="numeric_scale"]').value;
    const metric = row.querySelector('[name="numeric_metric"]');
    for (const option of metric.options) option.disabled = scale in allowed && !allowed[scale].includes(option.value);
  }
  document.getElementById('add-numeric-rule').addEventListener('click', () => {
    const fragment = document.getElementById('numeric-template').content.cloneNode(true);
    container.append(fragment);
    container.lastElementChild.querySelector('select').focus();
  });
  container.addEventListener('click', event => {
    if (event.target.matches('.remove-rule')) event.target.closest('.numeric-wrapper').remove();
  });
  container.addEventListener('change', event => {
    if (event.target.name !== 'numeric_scale') return;
    const row = event.target.closest('.numeric-rule');
    update(row);
    const metric = row.querySelector('[name="numeric_metric"]');
    if (metric.selectedOptions[0].disabled) metric.value = allowed[event.target.value][0];
  });
  container.querySelectorAll('.numeric-rule').forEach(update);
})();
