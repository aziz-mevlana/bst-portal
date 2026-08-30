(function () {
    'use strict';

    function activateTab(tabs, selectedTab) {
        tabs.forEach(function (tab) {
            var isSelected = tab === selectedTab;
            var panel = document.getElementById(tab.getAttribute('aria-controls'));
            tab.setAttribute('aria-selected', isSelected ? 'true' : 'false');
            tab.setAttribute('tabindex', isSelected ? '0' : '-1');
            if (panel) {
                panel.hidden = !isSelected;
                if (isSelected) {
                    panel.classList.remove('is-entering');
                    window.requestAnimationFrame(function () {
                        panel.classList.add('is-entering');
                    });
                }
            }
        });
    }

    document.querySelectorAll('[data-home-tabs]').forEach(function (container) {
        var tabs = Array.from(container.querySelectorAll('[role="tab"]'));
        if (tabs.length < 2) return;

        tabs.forEach(function (tab, index) {
            tab.addEventListener('click', function () {
                activateTab(tabs, tab);
            });

            tab.addEventListener('keydown', function (event) {
                var nextIndex = index;
                if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
                else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
                else if (event.key === 'Home') nextIndex = 0;
                else if (event.key === 'End') nextIndex = tabs.length - 1;
                else return;

                event.preventDefault();
                tabs[nextIndex].focus();
                activateTab(tabs, tabs[nextIndex]);
            });
        });
    });

    var homepage = document.querySelector('.bst-home');
    var revealItems = Array.from(document.querySelectorAll('[data-home-reveal]'));
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (!homepage || !revealItems.length || reduceMotion || !('IntersectionObserver' in window)) {
        revealItems.forEach(function (item) { item.classList.add('is-visible'); });
        return;
    }

    homepage.classList.add('home-motion-ready');
    var revealObserver = new IntersectionObserver(function (entries, observer) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
        });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });

    revealItems.forEach(function (item) { revealObserver.observe(item); });
})();
