// Grid carbon dashboard: reads the dashboard_* views from Supabase (read-only
// public key) and draws them. Refreshes every ten minutes; the charts keep
// their previous render (dimmed) while new data loads.

import {
    FUELS, RANGES, createClient, isConfigured, dayString, toSeries, summarise,
    intensityForecast, pipelineStatus, skillRows, num,
} from './data.js';
import { lineChart, stackedArea, legend, tableView, formatTime } from './charts.js';

const $ = selector => document.querySelector(selector);
const config = window.DASHBOARD_CONFIG || {};
const REFRESH_MS = 10 * 60 * 1000;

const state = { range: '7d', hourly: [], daily: [], forecast: [], skill: [], pipeline: [], lastRuns: [] };
let charts = [];

// --- Loading -----------------------------------------------------------------------

async function load() {
    const client = createClient(config);
    const now = new Date();
    for (const chart of document.querySelectorAll('.chart')) chart.classList.add('is-loading');
    try {
        const [hourly, daily, forecast, skill, pipeline, lastEtl, lastForecast] = await Promise.all([
            client.hourlySince(new Date(now.getTime() - 31 * 86400000)),
            client.dailySince(dayString(now, 366)),
            client.forecast(),
            client.skill(),
            client.pipeline(),
            client.lastRun('etl'),
            client.lastRun('forecast'),
        ]);
        // The newest run of each job, even if the recent list is all one job.
        Object.assign(state, { hourly, daily, forecast, skill, pipeline, lastRuns: [...lastEtl, ...lastForecast], loadedAt: now });
        setStatus('');
        render();
    } catch (error) {
        setStatus(`${error.message} Showing the last data loaded.`);
    } finally {
        for (const chart of document.querySelectorAll('.chart')) chart.classList.remove('is-loading');
    }
}

function setStatus(message) { $('#status').textContent = message; }

// --- Rendering -----------------------------------------------------------------------

const intFmt = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
const pct = value => (value === null ? '–' : `${value.toFixed(value < 10 ? 1 : 0)}%`);
const ago = new Intl.RelativeTimeFormat('en-GB', { numeric: 'auto' });
function timeAgo(date, now = new Date()) {
    const minutes = Math.round((date - now) / 60000);
    if (Math.abs(minutes) < 60) return ago.format(minutes, 'minute');
    const hours = Math.round(minutes / 60);
    if (Math.abs(hours) < 48) return ago.format(hours, 'hour');
    return ago.format(Math.round(hours / 24), 'day');
}

function render() {
    for (const chart of charts) chart.destroy();
    charts = [];
    renderNow();
    renderIntensity();
    renderMix();
    renderAccuracy();
    renderPipeline();
}

function renderNow() {
    const now = new Date();
    const summary = summarise(state.hourly, state.daily, now);
    if (!summary) {
        $('#now-value').textContent = '–';
        return;
    }
    $('#now-value').textContent = summary.intensity === null ? '–' : intFmt.format(summary.intensity);
    $('#now-time').textContent = `${formatTime(summary.time)}${summary.isActual ? '' : ' (estimate)'}`;
    const delta = $('#now-delta');
    delta.className = 'delta';
    delta.replaceChildren();
    if (summary.change !== null) {
        const strong = document.createElement('strong');
        const direction = summary.change > 0 ? 'higher' : summary.change < 0 ? 'lower' : 'the same';
        strong.textContent = summary.change === 0 ? 'Same' : `${summary.change > 0 ? '▲' : '▼'} ${intFmt.format(Math.abs(summary.change))} g ${direction}`;
        delta.classList.add(summary.change > 0 ? 'delta--worse' : summary.change < 0 ? 'delta--better' : 'delta--same');
        delta.append(strong, ' than this time yesterday');
    }
    $('#tile-windsolar').textContent = pct(summary.windSolar);
    $('#tile-lowcarbon').textContent = pct(summary.lowCarbon);
    $('#tile-gas').textContent = pct(summary.gas);
    $('#tile-average').textContent = summary.monthAverage === null ? '–' : intFmt.format(summary.monthAverage);
    if (summary.ageHours > 3) {
        setStatus(`The latest reading is ${Math.floor(summary.ageHours)} hours old. The collection job may be delayed; see Pipeline below.`);
    }
}

function rangeData() {
    const range = RANGES[state.range];
    if (range.source === 'daily') return { daily: true, series: toSeries(state.daily, 'day') };
    const since = Date.now() - range.hours * 3600000;
    return { daily: false, series: toSeries(state.hourly.filter(row => new Date(row.timestamp) >= since), 'timestamp') };
}

function renderIntensity() {
    const { daily, series } = rangeData();
    const container = $('#intensity-chart');
    const measured = series.times.map((time, i) => ({ time, value: series.intensity[i] }));
    const g = v => `${intFmt.format(v)} g`;

    if (daily) {
        $('#intensity-sub').textContent = 'Daily average in grams of CO₂ per kilowatt-hour, with each day’s lowest and highest hour.';
        legend($('#intensity-legend'), [{ label: 'Daily average', color: '--line-measured' }], 'line');
        const band = { label: 'Daily range', color: '--band-range' };
        $('#intensity-legend').append(...legendItems([band], 'band'));
        charts.push(lineChart(container, {
            series: [{ label: 'Daily average', color: '--line-measured', points: measured }],
            bands: [{ color: '--band-range', points: series.times.map((time, i) => ({ time, low: series.intensityMin[i], high: series.intensityMax[i] })) }],
            daily: true, valueText: g, ariaLabel: 'Line chart of daily average carbon intensity over the last 12 months',
        }));
        tableView($('#intensity-table'), [
            { label: 'Day', value: r => formatTime(r.time, true) },
            { label: 'Average (g)', numeric: true, value: r => fmtNum(r.value) },
            { label: 'Lowest hour', numeric: true, value: r => fmtNum(r.low) },
            { label: 'Highest hour', numeric: true, value: r => fmtNum(r.high) },
        ], series.times.map((time, i) => ({ time, value: series.intensity[i], low: series.intensityMin[i], high: series.intensityMax[i] })).reverse());
        return;
    }

    // Hourly ranges: add the newest forecast for 24 hours and 7 days.
    const withForecast = state.range === '24h' || state.range === '7d';
    const forecast = withForecast ? intensityForecast(state.forecast) : [];
    $('#intensity-sub').textContent = withForecast && forecast.length
        ? 'Grams of CO₂ per kilowatt-hour, hourly, with the next 24 hours forecast and the range it is 80% likely to fall in.'
        : 'Grams of CO₂ per kilowatt-hour, hourly.';
    const lines = [{ label: 'Recorded', color: '--line-measured', points: measured }];
    const bands = [];
    const legendLines = [{ label: 'Recorded', color: '--line-measured' }];
    if (forecast.length) {
        lines.push({ label: 'Forecast', color: '--line-forecast', points: forecast.map(p => ({ time: p.time, value: p.value })) });
        bands.push({ color: '--band', points: forecast });
        legendLines.push({ label: 'Forecast', color: '--line-forecast' });
    }
    legend($('#intensity-legend'), legendLines, 'line');
    if (forecast.length) $('#intensity-legend').append(...legendItems([{ label: '80% range', color: '--band' }], 'band'));
    charts.push(lineChart(container, {
        series: lines, bands, marker: forecast.length ? forecast[0].time : null, valueText: g,
        ariaLabel: `Line chart of hourly carbon intensity over the last ${RANGES[state.range].label}${forecast.length ? ', with the next 24 hours forecast' : ''}`,
    }));
    const rows = measured.map(p => ({ time: p.time, value: p.value, kind: 'Recorded' }))
        .concat(forecast.map(p => ({ time: p.time, value: p.value, low: p.low, high: p.high, kind: 'Forecast' })))
        .sort((a, b) => b.time - a.time);
    tableView($('#intensity-table'), [
        { label: 'Time', value: r => formatTime(r.time) },
        { label: 'Type', value: r => r.kind },
        { label: 'gCO₂/kWh', numeric: true, value: r => fmtNum(r.value) },
        { label: '80% range', numeric: true, value: r => (r.low === undefined ? '' : `${fmtNum(r.low)}–${fmtNum(r.high)}`) },
    ], rows);
}

function renderMix() {
    const { daily, series } = rangeData();
    const layers = FUELS.map(fuel => ({ ...fuel, color: `--fuel-${fuel.key}`, values: series.fuels[fuel.key] }));
    $('#mix-sub').textContent = daily
        ? 'Daily average share of Great Britain’s generation by source.'
        : 'Hourly share of Great Britain’s generation by source.';
    legend($('#mix-legend'), layers.slice().reverse(), 'rect');
    charts.push(stackedArea($('#mix-chart'), {
        times: series.times, layers, daily,
        ariaLabel: `Stacked area chart of the generation mix over the last ${RANGES[state.range].label}`,
    }));
    tableView($('#mix-table'), [
        { label: daily ? 'Day' : 'Time', value: r => formatTime(r.time, daily) },
        ...FUELS.map(fuel => ({ label: fuel.label, numeric: true, value: r => (r[fuel.key] === null ? '–' : `${r[fuel.key].toFixed(1)}%`) })),
    ], series.times.map((time, i) => ({ time, ...Object.fromEntries(FUELS.map(f => [f.key, series.fuels[f.key][i]])) })).reverse());
}

function renderAccuracy() {
    const container = $('#accuracy');
    container.replaceChildren();
    const rows = skillRows(state.skill);
    if (!rows.length) {
        const p = document.createElement('p');
        p.className = 'note';
        p.textContent = 'Not enough history yet. Scores appear once forecast hours have passed and there is a day of readings to compare against.';
        container.append(p);
        return;
    }
    const table = document.createElement('table');
    const head = table.createTHead().insertRow();
    for (const [label, numeric] of [['Forecast', false], ['Checked', true], ['Model error', true], ['Yesterday’s value', true], ['Difference', true], ['In 80% range', true]]) {
        const th = document.createElement('th');
        th.scope = 'col';
        th.textContent = label;
        if (numeric) th.className = 'num';
        head.append(th);
    }
    const body = table.createTBody();
    for (const row of rows) {
        const tr = body.insertRow();
        const cells = [
            [row.label, false],
            [row.forecasts === null ? '–' : intFmt.format(row.forecasts), true],
            [row.error === null ? '–' : `${row.error.toFixed(1)}${row.unit}`, true],
            [row.naiveError === null ? '–' : `${row.naiveError.toFixed(1)}${row.unit}`, true],
            [null, true],
            [row.coverage === null ? '–' : `${Math.round(row.coverage * 100)}%`, true],
        ];
        cells.forEach(([text, numeric], i) => {
            const td = tr.insertCell();
            if (numeric) td.className = 'num';
            if (i === 4) {
                if (row.skill === null) { td.textContent = '–'; return; }
                const span = document.createElement('span');
                const better = row.skill > 0;
                span.className = better ? 'skill-better' : 'skill-worse';
                span.textContent = `${better ? '▼' : '▲'} ${Math.abs(Math.round(row.skill * 100))}% ${better ? 'lower' : 'higher'}`;
                td.append(span);
            } else {
                td.textContent = text;
            }
        });
    }
    container.append(table);
    const note = document.createElement('p');
    note.className = 'note';
    note.textContent = 'Error is the average gap between forecast and outcome (grams for intensity, percentage points for shares). “Difference” compares it with repeating the value from 24 hours earlier; lower is better. A well-calibrated 80% range contains about 80% of outcomes.';
    container.append(note);
}

function renderPipeline() {
    const now = new Date();
    const status = pipelineStatus([...state.lastRuns, ...state.pipeline], now);
    const icons = { good: '✓', warning: '!', critical: '×', unknown: '?' };
    const list = $('#health');
    list.replaceChildren();
    for (const [title, entry] of [['Data collection', status.etl], ['Forecasting', status.forecast]]) {
        const li = document.createElement('li');
        const icon = document.createElement('span');
        icon.className = `health__icon health__icon--${entry.state}`;
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = icons[entry.state];
        const heading = document.createElement('p');
        heading.className = 'health__title';
        heading.textContent = `${title}: ${entry.label}`;
        const detail = document.createElement('p');
        detail.className = 'health__detail';
        if (entry.run) {
            const changed = (num(entry.run.rows_inserted) || 0) + (num(entry.run.rows_updated) || 0);
            detail.textContent = `Last run ${timeAgo(new Date(entry.run.run_timestamp), now)} · ${intFmt.format(changed)} ${title === 'Forecasting' ? 'forecasts stored' : 'hours added or updated'}`;
        }
        li.append(icon, heading, detail);
        list.append(li);
    }
    tableView($('#runs-table'), [
        { label: 'When', value: r => formatTime(new Date(r.run_timestamp)) },
        { label: 'Job', value: r => (r.job === 'forecast' ? 'Forecast' : 'Collection') },
        { label: 'Result', value: r => ({ success: 'Success', partial: 'Warnings', failure: 'Failed' }[r.status] || r.status) },
        { label: 'Rows', numeric: true, value: r => intFmt.format((num(r.rows_inserted) || 0) + (num(r.rows_updated) || 0)) },
        { label: 'Seconds', numeric: true, value: r => (num(r.execution_time_ms) === null ? '–' : (num(r.execution_time_ms) / 1000).toFixed(1)) },
    ], state.pipeline);
}

function legendItems(items, kind) {
    const holder = document.createElement('ul');
    legend(holder, items, kind);
    return [...holder.children];
}

const fmtNum = v => (v === null || v === undefined ? '–' : intFmt.format(v));

// --- Controls ------------------------------------------------------------------------

for (const button of document.querySelectorAll('[data-range]')) {
    button.addEventListener('click', () => setRange(button.dataset.range));
}

function setRange(range) {
    if (!RANGES[range]) return;
    state.range = range;
    for (const button of document.querySelectorAll('[data-range]')) {
        button.setAttribute('aria-pressed', String(button.dataset.range === range));
    }
    try { localStorage.setItem('range', range); } catch {}
    if (state.loadedAt) {
        for (const chart of charts) chart.destroy();
        charts = [];
        renderIntensity();
        renderMix();
    }
}

const themeButton = $('#theme-toggle');
const isDark = () => document.documentElement.dataset.theme === 'dark'
    || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
const syncTheme = () => {
    themeButton.textContent = isDark() ? 'Light mode' : 'Dark mode';
    themeButton.setAttribute('aria-pressed', String(isDark()));
};
themeButton.addEventListener('click', () => {
    const next = isDark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch {}
    syncTheme();
});
matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', syncTheme);
syncTheme();

// --- Start ---------------------------------------------------------------------------

let saved = null;
try { saved = localStorage.getItem('range'); } catch {}
setRange(RANGES[saved] ? saved : '7d');

if (!isConfigured(config)) {
    setStatus('This dashboard isn’t connected to a database yet: set SUPABASE_URL and SUPABASE_ANON_KEY as repository variables and redeploy (see the README).');
} else {
    load();
    setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && state.loadedAt && Date.now() - state.loadedAt > REFRESH_MS) load();
    });
}
