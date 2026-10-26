// 배치와 검토 위치만 관리한다. 보고서 상태·요청·분류 계산을 소유하지 않는다.
const workspace = document.querySelector('[data-workspace]');
if (workspace) {
  const layoutButtons = [...document.querySelectorAll('[data-layout-controls] [data-layout]')];
  const tabs = [...document.querySelectorAll('[data-view]')];
  const candidates = document.getElementById('candidate-results'), editor = document.getElementById('composition-editor');
  const context = workspace.querySelector('.workspace-context');
  function fitContext() { context.classList.toggle('workspace-context-fits', context.offsetHeight <= window.innerHeight - 24); }
  new ResizeObserver(fitContext).observe(context);
  window.addEventListener('resize', fitContext);
  let editing = null, layoutFocus = null, tabbing = false;
  function captureEditor(el) {
    if (editor.contains(el) && el.tagName === 'TEXTAREA') {
      layoutFocus = null;
      editing = {el, start:el.selectionStart, end:el.selectionEnd, direction:el.selectionDirection, scroll:el.scrollTop};
    }
  }
  function rememberEditor() {
    const active = document.activeElement;
    captureEditor(active);
    if (document.querySelector('[data-type-form]') && !editor.contains(active)
        && active?.matches('input, select, textarea')) layoutFocus = active;
  }
  // Tab 이동을 시작한 편집 위치를 남기고, 중간에 거치는 다른 textarea로 덮어쓰지 않는다.
  editor.addEventListener('keydown', event => {
    if (event.key === 'Tab') {
      if (!tabbing) captureEditor(event.target);
      tabbing = true;
    }
  });
  document.addEventListener('keydown', event => {
    if (!['Tab', 'Shift', 'Control', 'Alt', 'Meta'].includes(event.key)) tabbing = false;
  });
  document.addEventListener('pointerdown', () => { tabbing = false; }, {capture:true});
  // 위임으로 편집기 재구성에도 유지하며, 포인터·프로그램에 의한 포커스 이동도 기록한다.
  editor.addEventListener('focusout', event => { if (!tabbing) captureEditor(event.target); });
  function restoreEditor() {
    if (layoutFocus?.isConnected) { layoutFocus.focus({preventScroll:true}); return; }
    const saved = editing;
    if (!saved || !saved.el.isConnected || editor.hidden) return;
    saved.el.focus({preventScroll:true});
    saved.el.setSelectionRange(saved.start, saved.end, saved.direction); saved.el.scrollTop = saved.scroll;
    tabbing = false;
  }
  function setLayout(value) {
    if (!['left','top'].includes(value)) return;
    const anchor = layoutFocus?.isConnected ? layoutFocus : editing?.el.isConnected && !editor.hidden ? editing.el :
      [...workspace.querySelectorAll('.candidate-card, .workspace-profile-row')].find(el => el.getBoundingClientRect().top >= 0);
    const before = anchor?.getBoundingClientRect().top;
    workspace.dataset.layout = value;
    layoutButtons.forEach(el => el.setAttribute('aria-pressed', String(el.dataset.layout === value)));
    if (anchor && before !== undefined) window.scrollBy(0, anchor.getBoundingClientRect().top - before);
    restoreEditor();
  }
  document.querySelector('[data-layout-controls]').hidden = false;
  if (document.querySelector('[data-workspace-tabs]')) document.querySelector('[data-workspace-tabs]').hidden = false;
  layoutButtons.forEach(button => {
    button.addEventListener('pointerdown', rememberEditor);
    button.addEventListener('click', () => {
      setLayout(button.dataset.layout);
      try { localStorage.setItem('tci-workspace-layout', button.dataset.layout); } catch (_) { /* 표시 전환은 계속 동작한다. */ }
    });
  });
  try { setLayout(localStorage.getItem('tci-workspace-layout') || 'left'); } catch (_) { setLayout('left'); }
  if (candidates) {
  const positions = {candidates:0, temperament:0, character:0, selected:0};
  const navigation = document.querySelector('[data-topic-navigation]');
  const topics = {};
  const followCurrent = {};
  let view = 'candidates';
  function showTopic(key) {
    const panels = [...candidates.querySelectorAll('[data-topic]')].filter(el => el.dataset.topicView === view);
    if (!panels.some(el => el.dataset.topic === key)) key = panels.find(el => el.dataset.current === 'true')?.dataset.topic || panels[0]?.dataset.topic;
    topics[view] = key;
    followCurrent[view] = panels.find(el => el.dataset.topic === key)?.dataset.current === 'true';
    candidates.querySelectorAll('[data-topic]').forEach(el => { el.hidden = el.dataset.topic !== key; });
    navigation.replaceChildren();
    const label = document.createElement('label'); label.textContent = '검토 주제';
    const select = document.createElement('select'); select.setAttribute('aria-label','검토 주제');
    for (const panel of panels) {
      const option = document.createElement('option'); option.value = panel.dataset.topic;
      option.textContent = panel.querySelector('h2').textContent + (panel.dataset.current === 'true' ? ' · 현재 유형' : '');
      option.selected = option.value === key; select.append(option);
    }
    select.addEventListener('change', () => showTopic(select.value)); label.append(select); navigation.append(label);
  }
  function showView(value) {
    if (!['candidates','temperament','character','selected'].includes(value)) return;
    rememberEditor(); positions[view] = window.scrollY;
    view = value; candidates.hidden = view === 'selected'; editor.hidden = view !== 'selected';
    navigation.hidden = view === 'selected';
    if (view !== 'selected') showTopic(followCurrent[view] ? undefined : topics[view]);
    tabs.forEach(el => el.setAttribute('aria-pressed', String(el.dataset.view === view)));
    window.scrollTo(0, positions[view]);
    if (view === 'selected') restoreEditor();
  }
  tabs.forEach(button => { button.addEventListener('pointerdown', rememberEditor); button.addEventListener('click', () => showView(button.dataset.view)); });
  document.addEventListener('click', event => {
    const target = event.target.closest('[data-open-topic]');
    if (target) {
      const key = target.dataset.openTopic;
      const targetView = key.startsWith('scale:') ? 'candidates' : key.startsWith('temperament:') ? 'temperament' : 'character';
      topics[targetView] = key; followCurrent[targetView] = false; showView(targetView);
    }
    if (!event.target.closest('a[href="#composition-editor"]')) return;
    event.preventDefault(); showView('selected'); editor.scrollIntoView({block:'start'});
  });
  candidates.addEventListener('topicsupdated', () => { if (view !== 'selected') showTopic(followCurrent[view] ? undefined : topics[view]); });
  editor.hidden = true;
  navigation.hidden = false; showTopic('scale:NS');
  const focus = new URLSearchParams(location.search).get('focus');
  if (focus) {
    const target = [...editor.querySelectorAll('textarea')].find(el => el.name === 'text_' + focus || el.name === focus);
    if (target) {
      showView('selected');
      target.closest('[data-section]').open = true;
      target.focus(); target.scrollIntoView({block:'center'});
    }
  }
  }
}
