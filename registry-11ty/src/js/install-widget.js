// Install tool preference persistence
(function() {
  const widget = document.querySelector('.install .widget');
  if (!widget) return;

  const radios = widget.querySelectorAll('input[type="radio"][name="install-tool"]');

  // Restore saved preference
  const savedTool = localStorage.getItem('installTool');
  if (savedTool) {
    const savedRadio = widget.querySelector(`input[value="${savedTool}"]`);
    if (savedRadio) {
      savedRadio.checked = true;
    }
  }

  // Save preference on change
  radios.forEach(radio => {
    radio.addEventListener('change', () => {
      if (radio.checked) {
        localStorage.setItem('installTool', radio.value);
      }
    });
  });
})();
