(function () {
    function initNavigationSearch() {
        const modal = document.getElementById('navigationSearch');
        if (!modal) return;
        const input = document.getElementById('navigationSearchInput');
        const results = document.getElementById('navigationSearchResults');
        const status = document.getElementById('navigationSearchStatus');
        const links = [...document.querySelectorAll('[data-nav-search]')];

        function render() {
            const query = input.value.trim().toLocaleLowerCase();
            const matches = links.filter(link => link.textContent.toLocaleLowerCase().includes(query));
            results.replaceChildren(...matches.map(link => {
                const result = link.cloneNode(true);
                result.removeAttribute('data-nav-search');
                result.className = 'navigation-search-result';
                return result;
            }));
            status.textContent = matches.length
                ? matches.length + ' page' + (matches.length === 1 ? '' : 's') + ' available'
                : 'No pages found. Try a different name.';
        }

        modal.addEventListener('show.bs.modal', () => {
            const sidebar = document.getElementById('workspaceNav');
            const drawer = sidebar && bootstrap.Offcanvas.getInstance(sidebar);
            if (drawer) drawer.hide();
            input.value = '';
            render();
        });
        modal.addEventListener('shown.bs.modal', () => input.focus());
        input.addEventListener('input', render);
        modal.addEventListener('keydown', event => {
            const items = [...results.querySelectorAll('a')];
            const index = items.indexOf(document.activeElement);
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                if (!items.length) return;
                const next = event.key === 'ArrowDown' ? (index + 1) % items.length : (index <= 0 ? items.length - 1 : index - 1);
                items[next].focus();
            } else if (event.key === 'Enter' && event.target === input && items.length) {
                event.preventDefault();
                items[0].click();
            }
        });
        document.addEventListener('keydown', event => {
            if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return;
            const target = event.target;
            if (target.closest('input, textarea, select, [contenteditable="true"]') && !modal.contains(target)) return;
            if (document.querySelector('.modal.show:not(#navigationSearch)')) return;
            event.preventDefault();
            bootstrap.Modal.getOrCreateInstance(modal).toggle();
        });
    }

    function initTableScrolling() {
        document.querySelectorAll('.table-responsive').forEach((wrapper, index) => {
            const table = wrapper.querySelector('table');
            if (!table) return;
            const originalAttributes = new Map(
                ['tabindex', 'role', 'aria-label', 'aria-describedby'].map(name => [name, wrapper.getAttribute(name)])
            );
            const hint = document.createElement('p');
            hint.className = 'table-scroll-hint';
            hint.id = 'table-scroll-hint-' + index;
            hint.textContent = 'More columns available. Scroll sideways to see the full picture.';
            wrapper.after(hint);
            const update = () => {
                const overflowing = wrapper.scrollWidth > wrapper.clientWidth + 1;
                wrapper.classList.toggle('is-overflowing', overflowing);
                if (overflowing) {
                    wrapper.tabIndex = 0;
                    wrapper.setAttribute('role', originalAttributes.get('role') || 'region');
                    wrapper.setAttribute('aria-label', originalAttributes.get('aria-label') || table.caption?.textContent || 'Scrollable data table');
                    wrapper.setAttribute('aria-describedby', [originalAttributes.get('aria-describedby'), hint.id].filter(Boolean).join(' '));
                } else {
                    originalAttributes.forEach((value, name) => {
                        if (value === null) wrapper.removeAttribute(name);
                        else wrapper.setAttribute(name, value);
                    });
                }
            };
            new ResizeObserver(update).observe(wrapper);
            new MutationObserver(update).observe(table, { childList: true, subtree: true });
            update();
        });
    }

    function initPasswords() {
        document.querySelectorAll('input[type="password"][data-password-toggle]').forEach(input => {
            const wrapper = document.createElement('div');
            wrapper.className = 'password-field';
            input.before(wrapper);
            wrapper.append(input);
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'password-reveal';
            button.setAttribute('aria-label', 'Show password');
            button.setAttribute('aria-pressed', 'false');
            button.setAttribute('aria-controls', input.id);
            button.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i>';
            button.addEventListener('click', () => {
                const show = input.type === 'password';
                input.type = show ? 'text' : 'password';
                button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
                button.setAttribute('aria-pressed', String(show));
                button.firstElementChild.className = show ? 'bi bi-eye-slash' : 'bi bi-eye';
            });
            wrapper.append(button);
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        initNavigationSearch();
        initTableScrolling();
        initPasswords();
        document.addEventListener('theme-storage-unavailable', () => {
            let notice = document.getElementById('theme-storage-notice');
            if (!notice) {
                notice = document.createElement('div');
                notice.id = 'theme-storage-notice';
                notice.className = 'alert alert-warning';
                notice.setAttribute('role', 'status');
                document.querySelector('.workspace-content').prepend(notice);
            }
            notice.textContent = 'Your theme changed for this page, but browser storage is unavailable. It cannot be remembered after you leave.';
        });
        document.addEventListener('shown.bs.modal', event => {
            if (event.target.id === 'navigationSearch') return;
            const field = event.target.querySelector('input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])');
            if (field) field.focus();
        });
        document.addEventListener('keydown', event => {
            const trigger = event.target.closest('[role="button"][data-bs-toggle="collapse"]:not(button):not(a)');
            if (trigger && event.target === trigger && (event.key === ' ' || event.key === 'Enter')) {
                event.preventDefault();
                trigger.click();
            }
        });
        document.querySelectorAll('[role="button"][data-bs-toggle="collapse"]:not(button):not(a)').forEach(trigger => {
            trigger.tabIndex = 0;
        });
    });
})();
