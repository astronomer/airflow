// Copy install command
const copyBtn = document.querySelector('.install .copy-btn');
const installCommand = document.getElementById('install-command');

if (copyBtn && installCommand) {
  copyBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(installCommand.textContent);

      const originalHTML = copyBtn.innerHTML;
      copyBtn.innerHTML = '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>';

      setTimeout(() => {
        copyBtn.innerHTML = originalHTML;
      }, 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  });
}
