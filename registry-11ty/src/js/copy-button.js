// Copy Button - Progressive Enhancement
// Adds copy buttons to elements with data-copy-target attribute
(function() {
  // Only add copy buttons if Clipboard API is available
  if (!navigator.clipboard) return;

  // Find all elements that should have copy buttons
  document.querySelectorAll('[data-copy-target]').forEach(container => {
    const targetId = container.dataset.copyTarget;
    const targetElement = document.getElementById(targetId);

    if (!targetElement) return;

    const copyButton = document.createElement('button');
    copyButton.className = 'copy';
    copyButton.title = 'Copy';
    copyButton.setAttribute('aria-label', 'Copy to clipboard');
    copyButton.innerHTML = '<svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>';

    copyButton.addEventListener('click', async () => {
      const textToCopy = targetElement.textContent || '';
      try {
        await navigator.clipboard.writeText(textToCopy);

        // Show success state
        copyButton.innerHTML = '<svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" style="color:#4ade80"></path></svg>';

        // Reset after 2 seconds
        setTimeout(() => {
          copyButton.innerHTML = '<svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>';
        }, 2000);
      } catch (err) {
        console.error('Failed to copy:', err);
      }
    });

    container.appendChild(copyButton);
  });
})();
