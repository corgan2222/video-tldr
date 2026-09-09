// A module script runs after the document is parsed, so there is no
// DOMContentLoaded to wait for.
const status = document.querySelector('#status');
if (status) {
  status.textContent = 'corganshelper';
}
