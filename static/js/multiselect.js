(function () {
    function debounce(callback, wait) {
        let timer;
        return function () {
            const args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { callback.apply(null, args); }, wait);
        };
    }

    function createElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function enhance(select) {
        if (select.dataset.enhanced === 'true') return;
        select.dataset.enhanced = 'true';
        select.classList.add('bst-multiselect-native');

        const root = createElement('div', 'bst-multiselect');
        const control = createElement('div', 'bst-multiselect-control');
        const chips = createElement('div', 'bst-multiselect-chips');
        const search = createElement('input', 'bst-multiselect-search');
        const menu = createElement('div', 'bst-multiselect-menu');
        const list = createElement('div', 'bst-multiselect-list');
        const footer = createElement('div', 'bst-multiselect-footer');
        const count = createElement('span', '', '0 seçim');
        const clear = createElement('button', 'bst-multiselect-clear', 'Tümünü temizle');
        const listId = select.id + '-listbox';
        const asyncUrl = select.dataset.asyncUrl || '';
        const isAsync = select.dataset.asyncUsers === 'true' && asyncUrl;
        let remoteItems = [];
        let activeIndex = -1;

        search.type = 'text';
        search.autocomplete = 'off';
        search.placeholder = select.dataset.placeholder || 'Seçim ara';
        search.setAttribute('role', 'combobox');
        search.setAttribute('aria-expanded', 'false');
        search.setAttribute('aria-controls', listId);
        search.setAttribute('aria-autocomplete', 'list');
        list.id = listId;
        list.setAttribute('role', 'listbox');
        list.setAttribute('aria-multiselectable', 'true');
        clear.type = 'button';

        footer.append(count, clear);
        menu.append(list, footer);
        control.append(chips, search);
        root.append(control, menu);
        select.insertAdjacentElement('afterend', root);

        function selectedOptions() {
            return Array.from(select.options).filter(function (option) { return option.selected; });
        }

        function setOpen(open) {
            root.classList.toggle('is-open', open);
            search.setAttribute('aria-expanded', String(open));
            if (open) renderOptions();
        }

        function ensureOption(item) {
            let option = Array.from(select.options).find(function (entry) { return entry.value === String(item.id); });
            if (!option) {
                option = new Option(item.name, item.id, false, false);
                option.dataset.role = item.role || '';
                option.dataset.avatar = item.avatar || '';
                select.add(option);
            }
            return option;
        }

        function toggleValue(item) {
            const option = ensureOption(item);
            option.selected = !option.selected;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            renderChips();
            renderOptions();
            search.focus();
        }

        function currentItems() {
            if (isAsync) return remoteItems;
            const query = search.value.trim().toLocaleLowerCase('tr-TR');
            return Array.from(select.options).filter(function (option) {
                return option.value && (!query || option.text.toLocaleLowerCase('tr-TR').includes(query));
            }).map(function (option) {
                return { id: option.value, name: option.text, role: option.dataset.role || '', avatar: option.dataset.avatar || '' };
            });
        }

        function renderChips() {
            chips.replaceChildren();
            const selected = selectedOptions();
            selected.forEach(function (option) {
                const chip = createElement('span', 'bst-multiselect-chip');
                chip.append(createElement('span', '', option.text));
                const remove = createElement('button', '', '×');
                remove.type = 'button';
                remove.setAttribute('aria-label', option.text + ' seçimini kaldır');
                remove.addEventListener('click', function (event) {
                    event.stopPropagation();
                    option.selected = false;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    renderChips();
                    renderOptions();
                });
                chip.append(remove);
                chips.append(chip);
            });
            count.textContent = selected.length + ' seçim';
            clear.hidden = selected.length === 0;
        }

        function renderOptions() {
            list.replaceChildren();
            const items = currentItems();
            activeIndex = Math.min(activeIndex, items.length - 1);
            if (!items.length) {
                const message = isAsync && search.value.trim().length < 2 ? 'Aramak için en az 2 karakter yazın.' : 'Sonuç bulunamadı.';
                list.append(createElement('div', 'bst-multiselect-empty', message));
                return;
            }
            items.forEach(function (item, index) {
                const option = Array.from(select.options).find(function (entry) { return entry.value === String(item.id); });
                const button = createElement('button', 'bst-multiselect-option');
                button.type = 'button';
                button.setAttribute('role', 'option');
                button.setAttribute('aria-selected', String(Boolean(option && option.selected)));
                button.classList.toggle('is-active', index === activeIndex);
                if (item.avatar) {
                    const avatar = createElement('img', 'bst-multiselect-avatar');
                    avatar.src = item.avatar;
                    avatar.alt = '';
                    button.append(avatar);
                }
                const text = createElement('span', 'bst-multiselect-option-text');
                text.append(createElement('span', '', item.name));
                if (item.role) text.append(createElement('small', '', item.role));
                button.append(text);
                button.addEventListener('click', function () { toggleValue(item); });
                list.append(button);
            });
        }

        const fetchRemote = debounce(function () {
            const query = search.value.trim();
            if (query.length < 2) {
                remoteItems = [];
                renderOptions();
                return;
            }
            fetch(asyncUrl + '?q=' + encodeURIComponent(query), { headers: { Accept: 'application/json' } })
                .then(function (response) {
                    if (!response.ok) throw new Error('Arama yapılamadı.');
                    return response.json();
                })
                .then(function (data) {
                    remoteItems = Array.isArray(data.results) ? data.results : [];
                    renderOptions();
                })
                .catch(function () {
                    remoteItems = [];
                    list.replaceChildren(createElement('div', 'bst-multiselect-empty', 'Arama sırasında bir hata oluştu.'));
                });
        }, 280);

        control.addEventListener('click', function () { setOpen(true); search.focus(); });
        search.addEventListener('focus', function () { setOpen(true); });
        search.addEventListener('input', function () {
            activeIndex = -1;
            if (isAsync) fetchRemote(); else renderOptions();
        });
        search.addEventListener('keydown', function (event) {
            const items = currentItems();
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                activeIndex = Math.min(activeIndex + 1, items.length - 1);
                renderOptions();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                activeIndex = Math.max(activeIndex - 1, 0);
                renderOptions();
            } else if (event.key === 'Enter' && activeIndex >= 0 && items[activeIndex]) {
                event.preventDefault();
                toggleValue(items[activeIndex]);
            } else if (event.key === 'Escape') {
                setOpen(false);
            } else if (event.key === 'Backspace' && !search.value) {
                const selected = selectedOptions();
                const last = selected[selected.length - 1];
                if (last) {
                    last.selected = false;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    renderChips();
                    renderOptions();
                }
            }
        });
        clear.addEventListener('click', function () {
            Array.from(select.options).forEach(function (option) { option.selected = false; });
            select.dispatchEvent(new Event('change', { bubbles: true }));
            renderChips();
            renderOptions();
            search.focus();
        });
        document.addEventListener('click', function (event) {
            if (!root.contains(event.target)) setOpen(false);
        });

        renderChips();
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('select[multiple][data-enhance-multiselect="true"]').forEach(enhance);
    });
})();
