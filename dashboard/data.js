// Reading the dashboard_* views from Supabase's REST API, and the small
// calculations the page makes from them. No DOM here, so it runs under
// `node --test` too.

// Fuels in the order they stack, bottom to top, which is also the order the legend, the tooltip and the table
// list them (top first) and the order their colours were checked in (styles.css). Low-carbon sources at the
// bottom, wind on the baseline; then imports, which come from other countries; fossil fuels on top, gas on the
// top edge. Wind and gas swing most, so both read against a straight line. Coal has its own column since
// 31 Oct 2026; "other" is hydro and the API's "other".
export const FUELS = [
    { key: 'wind', label: 'Wind' },
    { key: 'solar', label: 'Solar' },
    { key: 'nuclear', label: 'Nuclear' },
    { key: 'biomass', label: 'Biomass' },
    { key: 'other', label: 'Hydro and other' },
    { key: 'imports', label: 'Imports' },
    { key: 'coal', label: 'Coal' },
    { key: 'gas', label: 'Gas' },
];

// The Carbon Intensity API's verdict on a reading. The API sets each hour's index itself (stored since
// 31 Oct 2026); for hours without one, these bands are what it used through 2026 (seen in its data: low up
// to 89, moderate 90–169, high 170–229, very high from 230). The API moves the bands each year.
export const BANDS = [
    { key: 'very low', label: 'Very low', below: 30 },
    { key: 'low', label: 'Low', below: 90 },
    { key: 'moderate', label: 'Moderate', below: 170 },
    { key: 'high', label: 'High', below: 230 },
    { key: 'very high', label: 'Very high', below: Infinity },
];

export function band(intensity, index = null) {
    const fromApi = BANDS.find(b => b.key === String(index || '').toLowerCase());
    if (fromApi) return { ...fromApi, fromApi: true };
    if (intensity === null || intensity === undefined) return null;
    return { ...BANDS.find(b => intensity < b.below), fromApi: false };
}

// How fresh the data is, from one rule, so the banner and the Pipeline card always agree.
// The API publishes each half hour within minutes, and the collection job is scheduled hourly, so a reading
// up to 90 minutes old is fresh. Older than that, the job is running late (GitHub often starts scheduled
// runs hours late, or skips them). More than 12 hours, or a failed last run, counts as failed.
export const FRESH_HOURS = 1.5;
export const FAILED_HOURS = 12;

export function freshness(latestTime, lastRun, now) {
    const age = latestTime ? (now - latestTime) / 3600000 : null;
    const hours = n => `${Math.floor(n)} hour${Math.floor(n) === 1 ? '' : 's'}`;
    if (age === null) return { state: 'failed', label: 'No readings', message: 'No readings have been collected yet.', age };
    if (lastRun?.status === 'failure') {
        return { state: 'failed', label: 'Last run failed', message: `The collection job failed on its last run, so the latest reading is ${hours(age)} old.`, age };
    }
    if (age > FAILED_HOURS) {
        return { state: 'failed', label: `No new data for ${hours(age)}`, message: `No new readings for ${hours(age)}: the collection job isn’t running.`, age };
    }
    if (age > FRESH_HOURS) {
        return { state: 'delayed', label: 'Delayed', message: `The latest reading is ${hours(age)} old: the hourly collection job started late. The next run fills the gap.`, age };
    }
    return { state: 'fresh', label: 'Up to date', message: '', age };
}

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
        hours: rows.map(row => num(row.hours)),
        fuels,
    };
}

// Each fuel's average share over a series, scaled so the shares add up to
// 100 (as the stacked chart does). Daily rows count by the hours they cover.
// Returns [{ key, label, share }] in FUELS order, or [] with no data.
export function mixAverages(series) {
    const means = FUELS.map(({ key, label }) => {
        let sum = 0, weight = 0;
        series.fuels[key].forEach((value, i) => {
            if (value === null) return;
            const w = series.hours?.[i] ?? 1;
            sum += value * w;
            weight += w;
        });
        return { key, label, mean: weight ? sum / weight : null };
    });
    const total = means.reduce((sum, m) => sum + (m.mean ?? 0), 0);
    if (!total) return [];
    return means.map(({ key, label, mean }) => ({ key, label, share: mean === null ? null : (mean / total) * 100 }));
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
    const intensity = num(latest.intensity);
    const recent = dailyRows.filter(row => row.day >= cutoff && num(row.intensity) !== null);
    const monthAverage = recent.length
        ? Math.round(recent.reduce((sum, row) => sum + num(row.intensity) * (num(row.hours) || 1), 0)
            / recent.reduce((sum, row) => sum + (num(row.hours) || 1), 0))
        : null;
    return {
        time: latestTime,
        intensity,
        isActual: latest.is_actual !== false,
        band: band(intensity, latest.intensity_index),
        change: dayBefore ? intensity - num(dayBefore.intensity) : null,
        windSolar: share('wind', 'solar'),
        gas: share('gas'),
        lowCarbon: share('wind', 'solar', 'nuclear', 'biomass'),
        imports: share('imports'),
        monthAverage,
        // Percent above (+) or below (−) the 30-day average.
        vsAverage: monthAverage && intensity !== null ? ((intensity - monthAverage) / monthAverage) * 100 : null,
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

// Latest ETL and forecast runs, for the pipeline card. Data collection is judged by freshness() (the same
// rule as the banner) when the latest reading's time is given.
export function pipelineStatus(runs, now, latestReading = undefined) {
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
    const etlRun = latestOf('etl');
    let etl;
    if (latestReading === undefined) {
        etl = describe(etlRun, 12);
    } else {
        const fresh = freshness(latestReading, etlRun, now);
        etl = { state: { fresh: 'good', delayed: 'warning', failed: 'critical' }[fresh.state], label: fresh.label, run: etlRun, freshness: fresh };
    }
    return { etl, forecast: forecastStatus(latestOf('forecast'), now) };
}

// The forecast is scheduled every three hours. Half as long again without a run is late; a day, or a failed
// run, is failed. (Until 31 Oct 2026 it allowed 12 hours, so the card said "Running normally" at 6 hours.)
export const FORECAST_EVERY_HOURS = 3;
export function forecastStatus(run, now) {
    if (!run) return { state: 'unknown', label: 'No runs in the last 14 days', run: null };
    const hours = (now - new Date(run.run_timestamp)) / 3600000;
    if (run.status === 'failure') return { state: 'critical', label: 'Last run failed', run };
    if (hours > 24) return { state: 'critical', label: `No run for ${Math.floor(hours)} hours`, run };
    if (hours > FORECAST_EVERY_HOURS * 1.5) return { state: 'warning', label: `Late: no run for ${Math.floor(hours)} hours`, run };
    if (run.status === 'partial') return { state: 'warning', label: 'Last run finished with warnings', run };
    return { state: 'good', label: 'Running normally', run };
}

// One plain sentence for the intensity forecast's skill, e.g. "The model's forecasts are about 21% closer
// than just repeating yesterday's value."
export function skillSummary(rows) {
    const row = rows.find(r => r.metric === 'Overall_Intensity');
    if (!row || row.skill === null) return '';
    const pct = Math.round(Math.abs(row.skill) * 100);
    if (pct < 3) return 'For carbon intensity, the model does about as well as repeating yesterday’s value.';
    return row.skill > 0
        ? `For carbon intensity, the model beats the simple forecast (repeating yesterday’s value) by about ${pct}%: its average error is ${pct}% smaller.`
        : `For carbon intensity, the model does worse than the simple forecast (repeating yesterday’s value): its average error is about ${pct}% larger.`;
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
