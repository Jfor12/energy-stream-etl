// Reading the dashboard_* views from Supabase's REST API, and the small
// calculations the page makes from them. No DOM here, so it runs under
// `node --test` too.

// Fuels in the order they stack and take colours (validated as a set: see
// styles.css). Hydro, coal and "other" arrive as one "other" column.
export const FUELS = [
    { key: 'wind', label: 'Wind' },
    { key: 'gas', label: 'Gas' },
    { key: 'nuclear', label: 'Nuclear' },
    { key: 'solar', label: 'Solar' },
    { key: 'imports', label: 'Imports' },
    { key: 'biomass', label: 'Biomass' },
    { key: 'other', label: 'Hydro, coal and other' },
];

export const RANGES = {
    '24h': { label: '24 hours', hours: 24, source: 'hourly' },
    '7d': { label: '7 days', hours: 24 * 7, source: 'hourly' },
    '30d': { label: '30 days', hours: 24 * 30, source: 'hourly' },
    '12m': { label: '12 months', days: 365, source: 'daily' },
};

export const METRIC_LABELS = {
    Overall_Intensity: 'Carbon intensity',
    Wind: 'Wind share',
    Solar: 'Solar share',
    Gas: 'Gas share',
    Nuclear: 'Nuclear share',
};

export function createClient({ supabaseUrl, supabaseKey }, fetchImpl = globalThis.fetch) {
    const base = String(supabaseUrl || '').replace(/\/+$/, '');
    async function get(view, params) {
        const url = `${base}/rest/v1/${view}?${new URLSearchParams(params)}`;
        let response;
        try {
            response = await fetchImpl(url, { headers: { apikey: supabaseKey, Authorization: `Bearer ${supabaseKey}` } });
        } catch {
            throw new Error('Couldn’t reach the database. Check your connection and reload.');
        }
        if (!response.ok) throw new Error(`The database returned an error (${response.status}) for ${view}.`);
        return response.json();
    }
    return {
        hourlySince: since => get('dashboard_hourly', { select: '*', timestamp: `gte.${since.toISOString()}`, order: 'timestamp.asc' }),
        dailySince: day => get('dashboard_daily', { select: '*', day: `gte.${day}`, order: 'day.asc' }),
        latestHours: count => get('dashboard_hourly', { select: '*', order: 'timestamp.desc', limit: String(count) }),
        forecast: () => get('dashboard_forecast', { select: '*', order: 'timestamp.asc' }),
        skill: () => get('dashboard_forecast_skill', { select: '*' }),
        pipeline: () => get('dashboard_pipeline', { select: '*', order: 'run_timestamp.desc', limit: '20' }),
        lastRun: job => get('dashboard_pipeline', { select: '*', job: `eq.${job}`, order: 'run_timestamp.desc', limit: '1' }),
    };
}

export const isConfigured = config => Boolean(config && config.supabaseUrl && config.supabaseKey);

// YYYY-MM-DD for `days` before `now`, in UTC (the view's days are UK days; a
// day's margin either side doesn't matter for a 12-month chart).
export function dayString(now, daysBack = 0) {
    return new Date(now.getTime() - daysBack * 86400000).toISOString().slice(0, 10);
}

export function num(value) {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

// Hourly or daily rows -> { times, intensity, fuels: {key: [..]} } with Dates.
export function toSeries(rows, timeKey) {
    const times = rows.map(row => new Date(timeKey === 'day' ? `${row.day}T12:00:00Z` : row[timeKey]));
    const fuels = Object.fromEntries(FUELS.map(({ key }) => [key, rows.map(row => num(row[key]))]));
    return {
        times,
        intensity: rows.map(row => num(row.intensity)),
        intensityMin: rows.map(row => num(row.intensity_min)),
        intensityMax: rows.map(row => num(row.intensity_max)),
        fuels,
    };
}

// The headline: the latest hour, the same hour a day earlier, and the shares.
export function summarise(latestRows, dailyRows, now) {
    const rows = [...latestRows].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    const latest = rows[0];
    if (!latest) return null;
    const latestTime = new Date(latest.timestamp);
    const dayBefore = rows.find(row => latestTime - new Date(row.timestamp) === 24 * 3600000);
    const share = (...keys) => keys.every(k => num(latest[k]) === null) ? null
        : keys.reduce((sum, k) => sum + (num(latest[k]) || 0), 0);
    const cutoff = dayString(now, 30);
    const recent = dailyRows.filter(row => row.day >= cutoff && num(row.intensity) !== null);
    const monthAverage = recent.length
        ? Math.round(recent.reduce((sum, row) => sum + num(row.intensity) * (num(row.hours) || 1), 0)
            / recent.reduce((sum, row) => sum + (num(row.hours) || 1), 0))
        : null;
    return {
        time: latestTime,
        intensity: num(latest.intensity),
        isActual: latest.is_actual !== false,
        change: dayBefore ? num(latest.intensity) - num(dayBefore.intensity) : null,
        windSolar: share('wind', 'solar'),
        gas: share('gas'),
        lowCarbon: share('wind', 'solar', 'nuclear', 'biomass'),
        monthAverage,
        ageHours: (now - latestTime) / 3600000,
    };
}

// The newest forecast of carbon intensity, as points for the chart.
export function intensityForecast(forecastRows) {
    return forecastRows
        .filter(row => row.metric === 'Overall_Intensity')
        .map(row => ({ time: new Date(row.timestamp), value: num(row.value), low: num(row.low), high: num(row.high) }))
        .sort((a, b) => a.time - b.time);
}

// Latest ETL and forecast runs, for the pipeline card.
export function pipelineStatus(runs, now) {
    const latestOf = job => runs
        .filter(run => run.job === job)
        .sort((a, b) => new Date(b.run_timestamp) - new Date(a.run_timestamp))[0] || null;
    const describe = (run, expectedHours) => {
        if (!run) return { state: 'unknown', label: 'No runs in the last 14 days', run: null };
        const hours = (now - new Date(run.run_timestamp)) / 3600000;
        if (run.status === 'failure') return { state: 'critical', label: 'Last run failed', run };
        if (hours > expectedHours) return { state: 'warning', label: `No run for ${Math.floor(hours)} hours`, run };
        if (run.status === 'partial') return { state: 'warning', label: 'Last run finished with warnings', run };
        return { state: 'good', label: 'Running normally', run };
    };
    // GitHub runs scheduled jobs late or skips them; each run covers 24 hours, so allow some slack.
    return { etl: describe(latestOf('etl'), 12), forecast: describe(latestOf('forecast'), 12) };
}

export function skillRows(rows) {
    const order = Object.keys(METRIC_LABELS);
    return rows
        .map(row => ({
            metric: row.metric,
            label: METRIC_LABELS[row.metric] || row.metric,
            forecasts: num(row.forecasts),
            error: num(row.mean_abs_error),
            naiveError: num(row.naive_mean_abs_error),
            skill: num(row.skill),
            coverage: num(row.interval_coverage),
            unit: row.metric === 'Overall_Intensity' ? ' g' : ' pts',
        }))
        .sort((a, b) => order.indexOf(a.metric) - order.indexOf(b.metric));
}

// "Nice" axis ticks: 0, 50, 100 ... covering [min, max].
export function niceTicks(min, max, count = 4) {
    if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
    if (min === max) { min -= 1; max += 1; }
    const raw = (max - min) / count;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(s => s >= raw) || 10 * magnitude;
    const start = Math.floor(min / step) * step;
    const end = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = start; v <= end + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
    return ticks;
}
