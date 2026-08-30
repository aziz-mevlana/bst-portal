function initializeHeaderControls() {
    const profileButton = document.getElementById('profile-button');
    const dropdownMenu = document.getElementById('dropdown-menu');
    const mobileMenuButton = document.getElementById('mobile-menu-button');
    const mobileMenu = document.getElementById('mobile-menu');
    const menuIcon = document.getElementById('menu-icon');
    const closeIcon = document.getElementById('close-icon');
    const header = document.getElementById('main-header');
    const notificationButton = document.getElementById('notification-button');
    const notificationMenu = document.getElementById('notification-menu');

    function setNotificationMenu(open) {
        if (!notificationButton || !notificationMenu) return;
        notificationMenu.hidden = !open;
        notificationButton.setAttribute('aria-expanded', String(open));
        if (open) notificationMenu.querySelector('[role="menuitem"]')?.focus();
    }

    function setProfileMenu(open) {
        if (!profileButton || !dropdownMenu) return;
        dropdownMenu.classList.toggle('hidden', !open);
        profileButton.setAttribute('aria-expanded', String(open));
        if (open) {
            const firstItem = dropdownMenu.querySelector('[role="menuitem"]');
            if (firstItem) firstItem.focus();
        }
    }

    function setMobileMenu(open) {
        if (!mobileMenuButton || !mobileMenu) return;
        mobileMenu.classList.toggle('active', open);
        mobileMenuButton.setAttribute('aria-expanded', String(open));
        mobileMenuButton.setAttribute('aria-label', open ? 'Menüyü kapat' : 'Menüyü aç');
        mobileMenu.setAttribute('aria-hidden', String(!open));
        if (menuIcon) menuIcon.classList.toggle('hidden', open);
        if (closeIcon) closeIcon.classList.toggle('hidden', !open);
        document.body.style.overflow = open ? 'hidden' : '';
        if (open) {
            const firstLink = mobileMenu.querySelector('a');
            if (firstLink) firstLink.focus();
        }
    }

    if (profileButton && dropdownMenu) {
        profileButton.addEventListener('click', function (event) {
            event.stopPropagation();
            setProfileMenu(profileButton.getAttribute('aria-expanded') !== 'true');
            setNotificationMenu(false);
        });
    }

    notificationButton?.addEventListener('click', function (event) {
        event.stopPropagation();
        setNotificationMenu(notificationButton.getAttribute('aria-expanded') !== 'true');
        setProfileMenu(false);
        setMobileMenu(false);
    });

    if (mobileMenuButton && mobileMenu) {
        mobileMenuButton.addEventListener('click', function (event) {
            event.stopPropagation();
            setMobileMenu(mobileMenuButton.getAttribute('aria-expanded') !== 'true');
            setProfileMenu(false);
            setNotificationMenu(false);
        });
        mobileMenu.addEventListener('click', function (event) {
            if (event.target === mobileMenu) setMobileMenu(false);
        });
    }

    document.addEventListener('click', function (event) {
        if (profileButton && dropdownMenu && !profileButton.contains(event.target) && !dropdownMenu.contains(event.target)) {
            setProfileMenu(false);
        }
        if (notificationButton && notificationMenu && !notificationButton.contains(event.target) && !notificationMenu.contains(event.target)) setNotificationMenu(false);
        if (mobileMenuButton && mobileMenu && !mobileMenuButton.contains(event.target) && !mobileMenu.contains(event.target)) {
            setMobileMenu(false);
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            const profileWasOpen = profileButton && profileButton.getAttribute('aria-expanded') === 'true';
            const notificationWasOpen = notificationButton && notificationButton.getAttribute('aria-expanded') === 'true';
            const mobileWasOpen = mobileMenuButton && mobileMenuButton.getAttribute('aria-expanded') === 'true';
            setProfileMenu(false);
            setNotificationMenu(false);
            setMobileMenu(false);
            if (profileWasOpen) profileButton.focus();
            else if (notificationWasOpen) notificationButton.focus();
            else if (mobileWasOpen) mobileMenuButton.focus();
        }
    });

    window.addEventListener('resize', function () {
        if (window.innerWidth >= 1180) setMobileMenu(false);
    });

    window.addEventListener('scroll', function () {
        if (header) header.classList.toggle('scrolled', window.scrollY > 10);
    }, { passive: true });

    document.getElementById('notification-read-all')?.addEventListener('submit', async function (event) {
        event.preventDefault();
        try {
            const response = await fetch(this.action, {method: 'POST', headers: {'X-Requested-With': 'XMLHttpRequest'}, body: new FormData(this)});
            if (!response.ok) return this.submit();
            document.getElementById('notification-badge')?.remove();
            const mobileCount = document.getElementById('mobile-notification-count');
            if (mobileCount) mobileCount.textContent = '';
            document.querySelectorAll('.notification-item.unread').forEach(item => item.classList.remove('unread'));
            this.remove();
        } catch (error) {
            this.submit();
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeHeaderControls, { once: true });
} else {
    initializeHeaderControls();
}
