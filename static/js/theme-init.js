(function () {
    const config = document.currentScript.dataset;
    const account = config.account === 'true';
    let mode = config.mode || 'light';
    const palette = config.palette || 'blue';
    if (!account) {
        try {
            mode = localStorage.getItem('jhq-theme') || 'light';
        } catch (error) {
            console.warn('Family HQ: browser theme storage is unavailable.', error);
        }
    }
    if (!['light', 'dark', 'auto'].includes(mode)) mode = 'light';
    const dark = mode === 'dark' ||
        (mode === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.dataset.bsTheme = dark ? 'dark' : 'light';
    document.documentElement.dataset.palette = palette;
    window.FinanceAppearance = { account, mode, palette, saveUrl: config.saveUrl };
})();
