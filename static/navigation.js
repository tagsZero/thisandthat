// 실제 페이지 이동에서만 현재 폼의 저장 여부를 확인한다.
window.tciNavigation = {
  register({isDirty, save}) {
    let leaving = false, pending = null;
    const dialog = document.createElement('dialog');
    dialog.className = 'leave-dialog';
    dialog.innerHTML = '<h2>작성한 내용을 저장할까요?</h2><p>저장하지 않은 변경이 있습니다.</p><p role="status"></p><div class="composition-actions"><button type="button" data-leave="save">저장 후 이동</button><button type="button" data-leave="continue">계속 작성</button><button type="button" data-leave="discard">변경 버리기</button></div>';
    document.body.append(dialog);
    const message = dialog.querySelector('[role=status]');
    const go = action => { leaving = true; dialog.close(); action(); };
    const navigate = action => {
      if (!isDirty()) { go(action); return; }
      pending = action; message.textContent = ''; dialog.showModal();
    };
    dialog.addEventListener('click', async event => {
      const choice = event.target.dataset.leave;
      if (!choice) return;
      if (choice === 'continue') { dialog.close(); return; }
      if (choice === 'discard') { go(pending); return; }
      dialog.querySelectorAll('button').forEach(b => b.disabled = true);
      try {
        if (await save() && !isDirty()) go(pending);
        else message.textContent = '저장 후 이동하지 못했습니다. 현재 작성 내용을 유지했습니다. 오류를 확인하거나 계속 작성하세요.';
      } catch (_) { message.textContent = '저장 확인에 실패했습니다. 현재 작성 내용을 유지했습니다.'; }
      finally { dialog.querySelectorAll('button').forEach(b => b.disabled = false); }
    });
    document.addEventListener('click', event => {
      const link = event.target.closest('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target || link.download) return;
      const target = new URL(link.href, location.href);
      if (target.origin !== location.origin || (target.pathname === location.pathname && target.search === location.search && target.hash)) return;
      event.preventDefault(); navigate(() => { location.href = target.href; });
    });
    document.addEventListener('submit', event => {
      if (!event.target.matches('.account form')) return;
      event.preventDefault(); navigate(() => event.target.submit());
    });
    window.addEventListener('beforeunload', event => {
      if (!leaving && isDirty()) { event.preventDefault(); event.returnValue = ''; }
    });
    return {navigate, leave(action) { go(action); }};
  }
};
