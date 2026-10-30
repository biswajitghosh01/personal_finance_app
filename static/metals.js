(() => {
    'use strict';

    document.querySelectorAll('.metal-delete-form').forEach((form) => {
        form.addEventListener('submit', (event) => {
            if (!window.confirm('Delete this metal asset?')) {
                event.preventDefault();
            }
        });
    });
})();
