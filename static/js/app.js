// Auto-reload page when audit status is 'running'
(function() {
  const badge = document.querySelector('.badge-running');
  if (badge && !window.__pollInit) {
    window.__pollInit = true;
    setTimeout(() => location.reload(), 5000);
  }
})();
