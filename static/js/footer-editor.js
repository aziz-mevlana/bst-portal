(() => {
    const editor = document.getElementById('footer-editor');
    if (!editor) return;
    const rows = editor.querySelector('[data-footer-rows]');
    const total = document.getElementById('id_links-TOTAL_FORMS');
    const add = editor.querySelector('[data-footer-add]');
    add.addEventListener('click', () => {
        const index = Number(total.value);
        if (index >= 100) {
            editor.querySelector('[data-footer-status]').textContent = 'En fazla 100 bağlantı eklenebilir.';
            return;
        }
        // Only our server-rendered template is used here; no user content is parsed as HTML.
        const template = document.getElementById('footer-empty-form');
        const copy = template.content.cloneNode(true);
        copy.querySelectorAll('*').forEach(element => {
            for (const attribute of ['id', 'name', 'for']) {
                if (element.hasAttribute(attribute)) element.setAttribute(attribute, element.getAttribute(attribute).replaceAll('__prefix__', String(index)));
            }
        });
        rows.append(copy);
        total.value = index + 1;
        document.getElementById(`id_links-${index}-label`)?.focus();
    });
})();
