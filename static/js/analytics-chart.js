window.createFinanceAnalyticsChart = function (canvas, payload) {
    if (!canvas || !payload.labels?.length) return null;
    const palette = window.financeChartPalette();
    const datasets = ['income', 'expense'].flatMap((stack, groupIndex) =>
        (payload[stack + '_datasets'] || []).map((series, index) => {
            const colourIndex = (index + groupIndex * 3) % palette.length;
            return {
                label: series.label,
                data: stack === 'expense' ? series.data.map(value => -value) : series.data,
                backgroundColor: palette[colourIndex] + 'b3',
                borderColor: palette[colourIndex],
                borderWidth: 1,
                borderRadius: 3,
                financeColour: colourIndex,
                financeAlpha: 'b3',
                stack,
            };
        })
    );
    return new Chart(canvas, {
        type: 'bar',
        data: { labels: payload.labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { stacked: true },
                y: {
                    stacked: true,
                    ticks: { callback: value => formatCurrency(Math.abs(value)) },
                },
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: context => context.dataset.label + ': ' + formatCurrency(Math.abs(context.raw)),
                    },
                },
                legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, padding: 18 } },
            },
        },
    });
};
