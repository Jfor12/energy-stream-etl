// Small SVG charts: a line chart (with optional bands) and a 100% stacked area
// chart. Both redraw on resize and share one crosshair + tooltip that works
// with a pointer or the keyboard (focus the chart, then use the arrow keys).
// Colours are CSS custom properties, so light and dark mode need no redraw.

import { niceTicks } from './data.js';

const SVG = 'http://www.w3.org/2000/svg';
const TZ = 'Europe/London';

function el(name, attrs = {}, parent) {
    const node = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (parent) parent.append(node);
    return node;
}

const fmt = (options) => new Intl.DateTimeFormat('en-GB', { timeZone: TZ, ...options });
const hourFmt = fmt({ hour: '2-digit', minute: '2-digit' });
const dayFmt = fmt({ weekday: 'short', day: 'numeric' });
const dateFmt = fmt({ day: 'numeric', month: 'short' });
const monthFmt = fmt({ month: 'short' });
const fullFmt = fmt({ weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const fullDayFmt = fmt({ weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });

export function formatTime(time, daily = false) {
    return daily ? fullDayFmt.format(time) : fullFmt.format(time);
}

// Up to ~6 x-axis ticks at sensible boundaries for the span shown.
function timeTicks(start, end, width) {
    const span = end - start;
    const hour = 3600000;
    const day = 24 * hour;
    const maxTicks = Math.max(3, Math.floor(width / 80));
    let step, label;
    if (span <= 2 * day) {
        step = [3, 6, 12].map(h => h * hour).find(s => span / s <= maxTicks) || 12 * hour;
        label = t => hourFmt.format(t);
    } else if (span <= 14 * day) {
        step = [1, 2, 3, 7].map(d => d * day).find(s => span / s <= maxTicks) || 7 * day;
        label = t => dayFmt.format(t);
    } else if (span <= 120 * day) {
        step = [7, 14, 28].map(d => d * day).find(s => span / s <= maxTicks) || 28 * day;
        label = t => dateFmt.format(t);
    } else {
        const months = [1, 2, 3].find(m => span / (m * 30.4 * day) <= maxTicks) || 3;
        const ticks = [];
        const d = new Date(start);
        d.setUTCDate(1); d.setUTCHours(0, 0, 0, 0);
        while (d <= end) {
            if (d >= start && d.getUTCMonth() % months === 0) ticks.push(new Date(d));
            d.setUTCMonth(d.getUTCMonth() + 1);
        }
        return ticks.map(t => ({ time: t, label: monthFmt.format(t) }));
    }
    // Align to UK-midnight-ish boundaries by rounding in UTC (close enough for labels).
    const first = Math.ceil(start / step) * step;
    const ticks = [];
    for (let t = first; t <= end; t += step) ticks.push({ time: new Date(t), label: label(new Date(t)) });
    return ticks;
}

// Shared frame: sizes, axes, crosshair and tooltip. `draw` paints the data.
function frame(container, { height: maxHeight, marginFor, yDomain, yFormat, times, draw, tooltip, daily, ariaLabel }) {
    let index = null;

    function render() {
        container.replaceChildren();
        const width = Math.max(260, container.clientWidth);
        // Shorter on narrow screens so the chart keeps a sensible shape.
        const height = Math.round(Math.min(maxHeight, Math.max(200, width * 0.6)));
        const margin = marginFor(width);
        const plotW = width - margin.left - margin.right;
        const plotH = height - margin.top - margin.bottom;
        const start = times[0];
        const end = times[times.length - 1];
        const x = t => margin.left + (end - start ? ((t - start) / (end - start)) * plotW : plotW / 2);
        const ticks = niceTicks(yDomain[0], yDomain[1]);
        const [y0, y1] = [ticks[0], ticks[ticks.length - 1]];
        const y = v => margin.top + plotH - ((v - y0) / (y1 - y0 || 1)) * plotH;

        const svg = el('svg', {
            viewBox: `0 0 ${width} ${height}`, width, height, class: 'chart__svg', role: 'img',
            'aria-label': ariaLabel, tabindex: '0',
        }, container);

        const grid = el('g', { class: 'chart__grid' }, svg);
        for (const tick of ticks) {
            el('line', { x1: margin.left, x2: width - margin.right, y1: y(tick), y2: y(tick),
                class: tick === y0 ? 'chart__baseline' : 'chart__gridline' }, grid);
            const text = el('text', { x: margin.left - 8, y: y(tick), class: 'chart__tick', 'text-anchor': 'end', 'dominant-baseline': 'middle' }, grid);
            text.textContent = yFormat(tick);
        }
        for (const tick of timeTicks(start, end, plotW)) {
            const text = el('text', { x: x(tick.time), y: height - margin.bottom + 18, class: 'chart__tick', 'text-anchor': 'middle' }, grid);
            text.textContent = tick.label;
        }

        draw({ svg, x, y, width, height, margin, plotW, plotH, y0 });

        // Crosshair layer.
        const cross = el('g', { class: 'chart__cross', visibility: 'hidden' }, svg);
        const line = el('line', { y1: margin.top, y2: margin.top + plotH, class: 'chart__crossline' }, cross);
        const dots = el('g', {}, cross);
        const tip = document.createElement('div');
        tip.className = 'chart__tooltip';
        tip.hidden = true;
        container.append(tip);

        function show(i) {
            if (i === null) { cross.setAttribute('visibility', 'hidden'); tip.hidden = true; return; }
            index = i;
            const t = times[i];
            const cx = x(t);
            line.setAttribute('x1', cx); line.setAttribute('x2', cx);
            dots.replaceChildren();
            const { title, rows } = tooltip(i);
            for (const row of rows) {
                if (row.value === null || row.y === undefined) continue;
                el('circle', { cx, cy: y(row.y), r: 4, class: 'chart__dot', style: `fill: var(${row.color})` }, dots);
            }
            cross.setAttribute('visibility', 'visible');
            tip.replaceChildren();
            const heading = document.createElement('p');
            heading.className = 'chart__tooltip-title';
            heading.textContent = title || formatTime(t, daily);
            tip.append(heading);
            for (const row of rows) {
                const p = document.createElement('p');
                p.className = 'chart__tooltip-row';
                const key = document.createElement('span');
                key.className = 'chart__key';
                key.style.background = `var(${row.color})`;
                const value = document.createElement('strong');
                value.textContent = row.text;
                const label = document.createElement('span');
                label.textContent = row.label;
                p.append(key, value, label);
                tip.append(p);
            }
            tip.hidden = false;
            const tipW = tip.offsetWidth;
            const left = cx + 12 + tipW > width ? cx - 12 - tipW : cx + 12;
            tip.style.left = `${Math.max(0, left)}px`;
            tip.style.top = `${margin.top}px`;
        }

        function nearest(clientX) {
            const box = svg.getBoundingClientRect();
            const px = ((clientX - box.left) / box.width) * width;
            const t = start.getTime() + ((px - margin.left) / plotW) * (end - start);
            let best = 0;
            for (let i = 1; i < times.length; i++) {
                if (Math.abs(times[i] - t) < Math.abs(times[best] - t)) best = i;
            }
            return best;
        }

        svg.addEventListener('pointermove', event => show(nearest(event.clientX)));
        svg.addEventListener('pointerleave', () => show(null));
        svg.addEventListener('focus', () => show(index ?? times.length - 1));
        svg.addEventListener('blur', () => show(null));
        svg.addEventListener('keydown', event => {
            const moves = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity };
            if (event.key === 'Escape') { show(null); return; }
            if (!(event.key in moves)) return;
            event.preventDefault();
            const next = Math.min(times.length - 1, Math.max(0, (index ?? times.length - 1) + moves[event.key]));
            show(next);
        });
        if (index !== null && document.activeElement === svg) show(index);
    }

    render();
    let lastWidth = container.clientWidth;
    const observer = new ResizeObserver(() => {
        if (container.clientWidth !== lastWidth) { lastWidth = container.clientWidth; render(); }
    });
    observer.observe(container);
    return { destroy: () => observer.disconnect() };
}

function pathFor(points, x, y) {
    let d = '';
    let pen = false;
    for (const p of points) {
        if (p.value === null) { pen = false; continue; }
        d += `${pen ? 'L' : 'M'}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)}`;
        pen = true;
    }
    return d;
}

function bandFor(points, x, y) {
    const valid = points.filter(p => p.low !== null && p.high !== null);
    if (valid.length < 2) return '';
    const top = valid.map((p, i) => `${i ? 'L' : 'M'}${x(p.time).toFixed(1)},${y(p.high).toFixed(1)}`).join('');
    const bottom = valid.slice().reverse().map(p => `L${x(p.time).toFixed(1)},${y(p.low).toFixed(1)}`).join('');
    return `${top}${bottom}Z`;
}

/**
 * series: [{ label, color: '--css-var', points: [{time, value}] }]
 * bands:  [{ color, points: [{time, low, high}] }]
 * marker: a Date to mark with a "now" line
 */
export function lineChart(container, { series, bands = [], marker, height = 280, yFormat = String, valueText = String, daily = false, ariaLabel }) {
    const allTimes = [...new Set(series.flatMap(s => s.points.map(p => p.time.getTime())))].sort((a, b) => a - b).map(t => new Date(t));
    const values = [
        ...series.flatMap(s => s.points.map(p => p.value)),
        ...bands.flatMap(b => b.points.flatMap(p => [p.low, p.high])),
    ].filter(v => v !== null);
    if (!allTimes.length || !values.length) return empty(container);
    const lookup = series.map(s => new Map(s.points.map(p => [p.time.getTime(), p.value])));
    const endTime = allTimes[allTimes.length - 1].getTime();
    const labelled = width => (series.length > 1 && width >= 480
        ? series.filter(s => s.points.some(p => p.value !== null && p.time.getTime() === endTime))
        : []);

    return frame(container, {
        height, daily, ariaLabel, times: allTimes,
        // Room for end labels only where they're drawn (wide charts, lines that reach the right edge).
        marginFor: width => ({ top: 12, right: labelled(width).length ? 76 : 16, bottom: 30, left: 44 }),
        yDomain: [Math.min(0, ...values), Math.max(...values)],
        yFormat,
        draw({ svg, x, y, margin, plotH, width }) {
            for (const band of bands) {
                el('path', { d: bandFor(band.points, x, y), class: 'chart__band', style: `fill: var(${band.color})` }, svg);
            }
            if (marker && marker >= allTimes[0] && marker <= allTimes[allTimes.length - 1]) {
                el('line', { x1: x(marker), x2: x(marker), y1: margin.top, y2: margin.top + plotH, class: 'chart__now' }, svg);
                const text = el('text', { x: x(marker) + 4, y: margin.top + 10, class: 'chart__tick' }, svg);
                text.textContent = 'Now';
            }
            const withLabels = labelled(width);
            for (const s of series) {
                el('path', { d: pathFor(s.points, x, y), class: 'chart__line', style: `stroke: var(${s.color})` }, svg);
                // Direct label at the end of a line, when it ends at the right edge (so
                // labels never collide where one line hands over to the next).
                const last = [...s.points].reverse().find(p => p.value !== null);
                if (withLabels.includes(s) && last) {
                    const text = el('text', { x: x(last.time) + 8, y: y(last.value), class: 'chart__label', 'dominant-baseline': 'middle' }, svg);
                    text.textContent = s.label;
                }
            }
        },
        tooltip(i) {
            const t = allTimes[i].getTime();
            return {
                rows: series.map((s, n) => {
                    const value = lookup[n].get(t) ?? null;
                    return { label: s.label, color: s.color, value, y: value, text: value === null ? '–' : valueText(value) };
                }).filter(row => row.value !== null),
            };
        },
    });
}

/** layers: [{ key, label, color, values: [number|null] }] aligned with times; stacked bottom-up. */
export function stackedArea(container, { times, layers, height = 280, daily = false, ariaLabel }) {
    if (!times.length) return empty(container);
    const totals = times.map((_, i) => layers.reduce((sum, layer) => sum + (layer.values[i] ?? 0), 0));
    const present = times.map((_, i) => layers.some(layer => layer.values[i] !== null));
    return frame(container, {
        height, daily, ariaLabel, times,
        marginFor: () => ({ top: 12, right: 16, bottom: 30, left: 44 }),
        yDomain: [0, 100],
        yFormat: v => `${v}%`,
        draw({ svg, x, y }) {
            // Normalise each time to 100% so rounding never leaves a sliver.
            let base = times.map(() => 0);
            for (const layer of layers) {
                const top = base.map((b, i) => b + (totals[i] ? ((layer.values[i] ?? 0) / totals[i]) * 100 : 0));
                let d = '';
                // Break the area wherever a time has no data at all.
                let run = [];
                const flush = () => {
                    if (run.length > 1) {
                        d += run.map((i, k) => `${k ? 'L' : 'M'}${x(times[i]).toFixed(1)},${y(top[i]).toFixed(1)}`).join('');
                        d += run.slice().reverse().map(i => `L${x(times[i]).toFixed(1)},${y(base[i]).toFixed(1)}`).join('') + 'Z';
                    }
                    run = [];
                };
                times.forEach((_, i) => (present[i] ? run.push(i) : flush()));
                flush();
                el('path', { d, class: 'chart__area', style: `fill: var(${layer.color})` }, svg);
                base = top;
            }
        },
        tooltip(i) {
            let cumulative = 0;
            const rows = layers.map(layer => {
                const share = totals[i] ? ((layer.values[i] ?? 0) / totals[i]) * 100 : null;
                cumulative += share ?? 0;
                return { label: layer.label, color: layer.color, value: layer.values[i], y: cumulative - (share ?? 0) / 2,
                    text: layer.values[i] === null ? '–' : `${layer.values[i].toFixed(1)}%` };
            });
            return { rows: rows.reverse() };  // top of the stack first, as drawn
        },
    });
}

function empty(container) {
    container.replaceChildren();
    const p = document.createElement('p');
    p.className = 'chart__empty';
    p.textContent = 'No data for this period yet.';
    container.append(p);
    return { destroy() {} };
}

// Legend: swatch (rect for areas, line for lines) + ink label.
export function legend(container, items, kind = 'rect') {
    container.replaceChildren();
    for (const item of items) {
        const li = document.createElement('li');
        const key = document.createElement('span');
        key.className = `legend__key legend__key--${kind}`;
        key.style.background = `var(${item.color})`;
        const label = document.createElement('span');
        label.textContent = item.label;
        li.append(key, label);
        container.append(li);
    }
}

// The table twin of a chart, built when first opened.
export function tableView(details, columns, rows) {
    const build = () => {
        const wrap = details.querySelector('.table-wrap');
        wrap.replaceChildren();
        const table = document.createElement('table');
        const head = table.createTHead().insertRow();
        for (const column of columns) {
            const th = document.createElement('th');
            th.scope = 'col';
            th.textContent = column.label;
            if (column.numeric) th.className = 'num';
            head.append(th);
        }
        const body = table.createTBody();
        for (const row of rows) {
            const tr = body.insertRow();
            for (const column of columns) {
                const td = tr.insertCell();
                td.textContent = column.value(row);
                if (column.numeric) td.className = 'num';
            }
        }
        wrap.append(table);
    };
    details.ontoggle = () => { if (details.open) build(); };
    if (details.open) build();
}
