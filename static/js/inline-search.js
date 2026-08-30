(() => {
    const root = document.querySelector('[data-inline-search]');
    if (!root) return;
    const toggle = root.querySelector('[data-search-toggle]');
    const panel = root.querySelector('.nav-search-panel');
    const form = root.querySelector('form');
    const input = root.querySelector('input');
    const status = root.querySelector('[data-search-status]');
    const items = root.querySelector('[data-search-items]');
    const more = root.querySelector('[data-search-more]');
    const nav = root.closest('.nav-content');
    let controller, timer, generation = 0;

    function close(focus = false) {
        clearTimeout(timer);
        controller?.abort();
        generation++;
        root.classList.remove('is-open');
        nav?.classList.remove('search-active');
        panel.inert = true;
        panel.setAttribute('aria-hidden', 'true');
        toggle.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-busy');
        if (focus) toggle.focus();
    }
    function open() {
        ['profile-button', 'notification-button', 'mobile-menu-button'].forEach(id => {
            const button = document.getElementById(id);
            if (button?.getAttribute('aria-expanded') === 'true') button.click();
        });
        root.classList.add('is-open');
        nav?.classList.add('search-active');
        panel.inert = false;
        panel.setAttribute('aria-hidden', 'false');
        toggle.setAttribute('aria-expanded', 'true');
        input.focus();
        if (input.value.trim().length >= 2) search();
    }
    function resetResults() {
        items.replaceChildren();
        more.href = form.action;
        more.textContent = 'Gelişmiş filtreleri aç →';
    }
    async function search() {
        clearTimeout(timer);
        controller?.abort();
        const current = ++generation;
        const query = input.value.trim();
        resetResults();
        if (query.length < 2) {
            status.textContent = 'Aramak için en az 2 karakter yazın.';
            input.removeAttribute('aria-busy');
            return;
        }
        const url = new URL(form.action, window.location.origin);
        url.searchParams.set('q', query);
        more.href = url.href;
        url.searchParams.set('format', 'json');
        controller = new AbortController();
        status.textContent = 'Aranıyor…';
        input.setAttribute('aria-busy', 'true');
        try {
            const response = await fetch(url, {signal: controller.signal, headers: {'Accept': 'application/json'}});
            if (!response.ok) throw new Error('Search failed');
            const data = await response.json();
            if (current !== generation || !root.classList.contains('is-open')) return;
            for (const result of data.results) {
                const li = document.createElement('li');
                const a = document.createElement('a');
                const label = document.createElement('strong');
                const detail = document.createElement('span');
                a.href = result.url;
                label.textContent = result.label;
                detail.textContent = result.category + (result.subtitle ? ' · ' + result.subtitle.slice(0, 90) : '');
                a.append(label, detail);
                li.append(a);
                items.append(li);
            }
            status.textContent = data.total ? `${data.total} sonuç bulundu. İlk ${data.results.length} sonuç:` : 'Sonuç bulunamadı. Farklı bir ifade deneyin.';
            more.href = data.full_url;
            more.textContent = data.total ? 'Tüm sonuçlar ve filtreler →' : 'Gelişmiş filtrelerle ara →';
        } catch (error) {
            if (error.name !== 'AbortError' && current === generation) {
                status.textContent = 'Arama yüklenemedi. Tekrar deneyin veya gelişmiş aramayı açın.';
            }
        } finally {
            if (current === generation) input.removeAttribute('aria-busy');
        }
    }
    toggle.addEventListener('click', () => root.classList.contains('is-open') ? close(true) : open());
    root.querySelector('[data-search-close]').addEventListener('click', () => close(true));
    document.querySelector('[data-mobile-search]')?.addEventListener('click', event => { event.stopPropagation(); open(); });
    form.addEventListener('submit', event => { event.preventDefault(); search(); });
    input.addEventListener('input', () => {
        clearTimeout(timer);
        controller?.abort();
        generation++;
        resetResults();
        status.textContent = input.value.trim().length < 2 ? 'Aramak için en az 2 karakter yazın.' : 'Aranıyor…';
        timer = setTimeout(search, 250);
    });
    root.addEventListener('keydown', event => {
        const links = Array.from(items.querySelectorAll('a'));
        const index = links.indexOf(document.activeElement);
        if (event.key === 'ArrowDown' && links.length && (event.target === input || index >= 0)) {
            event.preventDefault(); links[(index + 1) % links.length].focus();
        } else if (event.key === 'ArrowUp' && index >= 0) {
            event.preventDefault(); (links[index - 1] || input).focus();
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && root.classList.contains('is-open')) { event.preventDefault(); close(true); }
    });
    document.addEventListener('click', event => { if (!root.contains(event.target)) close(); });
    root.addEventListener('focusout', () => setTimeout(() => {
        if (!root.contains(document.activeElement)) close();
    }, 0));
    ['profile-button', 'notification-button', 'mobile-menu-button'].forEach(id => {
        document.getElementById(id)?.addEventListener('click', () => close());
    });
})();
