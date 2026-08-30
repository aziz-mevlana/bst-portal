(function () {
    function initializeDashboardSidebar() {
        const sidebar = document.getElementById('dashboard-sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        const openButton = document.querySelector('[data-sidebar-open]');
        const closeButton = document.querySelector('[data-sidebar-close]');

        if (!sidebar || !overlay || !openButton || openButton.dataset.sidebarReady === 'true') return;
        openButton.dataset.sidebarReady = 'true';
        sidebar.setAttribute('aria-hidden', window.innerWidth >= 768 ? 'false' : 'true');

        function setSidebar(open) {
            sidebar.classList.toggle('open', open);
            overlay.classList.toggle('active', open);
            sidebar.setAttribute('aria-hidden', String(!open));
            overlay.setAttribute('aria-hidden', String(!open));
            openButton.setAttribute('aria-expanded', String(open));
            document.body.style.overflow = open ? 'hidden' : '';
            if (open) closeButton?.focus();
        }

        window.toggleSidebar = function () {
            setSidebar(!sidebar.classList.contains('open'));
        };
        openButton.addEventListener('click', function () { setSidebar(true); });
        closeButton?.addEventListener('click', function () { setSidebar(false); openButton.focus(); });
        overlay.addEventListener('click', function () { setSidebar(false); });
        sidebar.addEventListener('click', function (event) {
            if (event.target.closest('a')) setSidebar(false);
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && sidebar.classList.contains('open')) {
                setSidebar(false);
                openButton.focus();
            }
        });
        window.addEventListener('resize', function () {
            if (window.innerWidth >= 768) setSidebar(false);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeDashboardSidebar, { once: true });
    } else {
        initializeDashboardSidebar();
    }
}());
