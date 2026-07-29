(function() {
    'use strict';

    // ── Dark Mode ──
    const toggle = document.getElementById('theme-toggle');
    const body = document.body;
    const stored = localStorage.getItem('theme');

    if (stored === 'dark') {
        body.classList.add('dark-mode');
        if (toggle) toggle.textContent = '☀️';
    }

    if (toggle) {
        toggle.addEventListener('click', function() {
            const isDark = body.classList.toggle('dark-mode');
            localStorage.setItem('theme', isDark ? 'dark' : 'light');
            toggle.textContent = isDark ? '☀️' : '🌙';
        });
    }

    // ── Clickable Table Rows ──
    document.querySelectorAll('.clickable-row').forEach(function(row) {
        row.addEventListener('click', function(e) {
            // Don't navigate if user clicked a link, button, or inside a form
            const target = e.target;
            if (target.closest('a') || target.closest('button') || target.closest('form')) {
                return;
            }
            const href = row.dataset.href;
            if (href) {
                window.location.href = href;
            }
        });
    });

    // ── Betting Calculator (Live + Submit) ──
    const calcForm = document.getElementById('betting-calc');
    if (calcForm) {
        const stakeInput = calcForm.querySelector('input[name="stake"]');
        const oddsInput = calcForm.querySelector('input[name="odds"]');
        const retDisplay = document.getElementById('calc-return');
        const profitDisplay = document.getElementById('calc-profit');

        function updateCalc() {
            const stake = parseFloat(stakeInput.value);
            const odds = parseFloat(oddsInput.value);

            if (isNaN(stake) || isNaN(odds) || stake < 0 || odds < 1) {
                retDisplay.textContent = '—';
                profitDisplay.textContent = '—';
                profitDisplay.style.color = '';
                return;
            }

            const ret = stake * odds;
            const profit = stake * (odds - 1);

            retDisplay.textContent = ret.toFixed(2);
            profitDisplay.textContent = (profit >= 0 ? '+' : '') + profit.toFixed(2);
            profitDisplay.style.color = profit >= 0 ? 'var(--green)' : 'var(--red)';
        }

        calcForm.addEventListener('submit', function(e) {
            e.preventDefault();
            updateCalc();
        });

        if (stakeInput) stakeInput.addEventListener('input', updateCalc);
        if (oddsInput) oddsInput.addEventListener('input', updateCalc);

        // Initial run
        updateCalc();
    }

    // ── Service Worker ──
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/predictions/sw.js')
            .then(function(reg) {
                console.log('SW registered:', reg.scope);
            })
            .catch(function(err) {
                console.log('SW registration failed:', err);
            });
    }
})();

window.addEventListener('load', function() {
    const loader = document.getElementById('page-loader');
    if (loader) {
        loader.style.opacity = '0';
        loader.style.transition = 'opacity 0.3s';
        setTimeout(() => loader.remove(), 300);
    }
});