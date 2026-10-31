import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    createClient, summarise, toSeries, intensityForecast, pipelineStatus, skillRows, niceTicks, dayString, mixAverages, FUELS,
    band, freshness, skillSummary, forecastStatus,
} from '../data.js';

const hour = t => new Date(Date.UTC(2026, 8, 25, t)).toISOString();
const row = (t, intensity, extra = {}) => ({
    timestamp: hour(t), intensity, is_actual: true, wind: 30, gas: 25, nuclear: 15, solar: 10,
    imports: 8, biomass: 7, other: 5, ...extra,
});

test('the client asks the dashboard views with the public key and PostgREST filters', async () => {
    const calls = [];
    const fetchImpl = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => [] }; };
    const client = createClient({ supabaseUrl: 'https://x.supabase.co/', supabaseKey: 'pub' }, fetchImpl);
    await client.hourlySince(new Date('2026-09-01T00:00:00Z'));
    await client.pipeline();
    assert.equal(calls[0].url, 'https://x.supabase.co/rest/v1/dashboard_hourly?select=*&timestamp=gte.2026-09-01T00%3A00%3A00.000Z&order=timestamp.asc');
    assert.equal(calls[0].options.headers.apikey, 'pub');
    assert.match(calls[1].url, /dashboard_pipeline\?select=\*&order=run_timestamp\.desc&limit=20$/);
});

test('a database error becomes a readable message', async () => {
    const client = createClient({ supabaseUrl: 'https://x', supabaseKey: 'k' }, async () => ({ ok: false, status: 401 }));
    await assert.rejects(client.forecast(), /error \(401\) for dashboard_forecast/);
});

test('summarise: latest hour, change on yesterday, shares and the 30-day average', () => {
    const now = new Date(Date.UTC(2026, 8, 25, 12, 20));
    const hourly = [row(12, 120), row(11, 130), ...Array.from({ length: 23 }, (_, i) => row(-12 + i, 150))];
    hourly.push(row(-12, 150));
    const summary = summarise(hourly, [
        { day: '2026-09-24', intensity: 100, hours: 24 },
        { day: '2026-09-25', intensity: 200, hours: 12 },
        { day: '2026-07-01', intensity: 999, hours: 24 },  // outside 30 days
    ], now);
    assert.equal(summary.intensity, 120);
    assert.equal(summary.change, 120 - 150);
    assert.equal(summary.windSolar, 40);
    assert.equal(summary.lowCarbon, 62);
    assert.equal(summary.monthAverage, Math.round((100 * 24 + 200 * 12) / 36));
    assert.ok(summary.ageHours < 1);
});

test('summarise copes with no data and with old rows missing fuels', () => {
    assert.equal(summarise([], [], new Date()), null);
    const summary = summarise([row(1, 100, { imports: null, biomass: null, other: null })], [], new Date(Date.UTC(2026, 8, 25, 2)));
    assert.equal(summary.lowCarbon, 55);  // biomass unknown counts as 0, not NaN
    assert.equal(summary.change, null);
});

test('series keep gaps as null and daily rows sit at midday', () => {
    const series = toSeries([{ day: '2026-09-24', intensity: '140', wind: null }], 'day');
    assert.equal(series.times[0].toISOString(), '2026-09-24T12:00:00.000Z');
    assert.equal(series.intensity[0], 140);
    assert.equal(series.fuels.wind[0], null);
});

test('only the intensity forecast is charted, in time order', () => {
    const points = intensityForecast([
        { metric: 'Wind', timestamp: hour(3), value: 1 },
        { metric: 'Overall_Intensity', timestamp: hour(5), value: 110, low: 100, high: 120 },
        { metric: 'Overall_Intensity', timestamp: hour(4), value: 105, low: 95, high: 115 },
    ]);
    assert.deepEqual(points.map(p => p.value), [105, 110]);
});

test('pipeline status: normal, late, failed and never run', () => {
    const now = new Date(Date.UTC(2026, 8, 25, 12));
    const status = pipelineStatus([
        { job: 'etl', status: 'success', run_timestamp: hour(11) },
        { job: 'forecast', status: 'failure', run_timestamp: hour(9) },
    ], now);
    assert.equal(status.etl.state, 'good');
    assert.equal(status.forecast.state, 'critical');
    assert.equal(pipelineStatus([{ job: 'etl', status: 'success', run_timestamp: hour(-20) }], now).etl.state, 'warning');
    assert.equal(pipelineStatus([], now).forecast.state, 'unknown');
});

test('skill rows are labelled and ordered with intensity first', () => {
    const rows = skillRows([
        { metric: 'Wind', forecasts: 24, mean_abs_error: '2.1', naive_mean_abs_error: '3', skill: '0.3', interval_coverage: '0.8' },
        { metric: 'Overall_Intensity', forecasts: 24, mean_abs_error: '9', naive_mean_abs_error: '12', skill: '0.25', interval_coverage: '0.75' },
    ]);
    assert.deepEqual(rows.map(r => r.label), ['Carbon intensity', 'Wind share']);
    assert.equal(rows[1].error, 2.1);
});

test('axis ticks are round numbers covering the data', () => {
    assert.deepEqual(niceTicks(0, 237), [0, 100, 200, 300]);
    assert.deepEqual(niceTicks(0, 100), [0, 25, 50, 75, 100]);
    assert.equal(dayString(new Date('2026-09-25T10:00:00Z'), 1), '2026-09-24');
});

test('mix averages: shares over the period add up to 100, days weighted by their hours', () => {
    const hourly = toSeries([row(1, 150), row(2, 150, { wind: 50, gas: 5 })], 'timestamp');
    const shares = Object.fromEntries(mixAverages(hourly).map(m => [m.key, m.share]));
    assert.equal(Math.round(shares.wind * 10) / 10, 40);
    assert.equal(Math.round(Object.values(shares).reduce((a, b) => a + b) * 1e6) / 1e6, 100);
    assert.deepEqual(mixAverages(hourly).map(m => m.key), FUELS.map(f => f.key));

    const daily = toSeries([
        { day: '2026-09-24', hours: 23, wind: 20, gas: 30, nuclear: 15, solar: 10, imports: 8, biomass: 7, other: 10 },
        { day: '2026-09-25', hours: 1, wind: 44, gas: 6, nuclear: 15, solar: 10, imports: 8, biomass: 7, other: 10 },
    ], 'day');
    assert.equal(mixAverages(daily).find(m => m.key === 'wind').share, 21);  // (20·23 + 44·1) / 24

    assert.deepEqual(mixAverages(toSeries([], 'timestamp')), []);
    const oldRows = toSeries([row(1, 150, { imports: null, biomass: null, other: null })], 'timestamp');
    assert.equal(mixAverages(oldRows).find(m => m.key === 'imports').share, null);
});

test('the stack keeps wind and gas on its edges', () => {
    assert.equal(FUELS[0].key, 'wind');
    assert.equal(FUELS[FUELS.length - 1].key, 'gas');
});

test('the rating is the API\'s own index, or its 2026 bands when a row has none', () => {
    assert.equal(band(197, 'high').label, 'High');
    assert.equal(band(197, 'High').fromApi, true);
    assert.deepEqual([20, 60, 150, 200, 260].map(v => band(v).key), ['very low', 'low', 'moderate', 'high', 'very high']);
    assert.equal(band(89).key, 'low');
    assert.equal(band(90).key, 'moderate');
    assert.equal(band(null), null);
});

test('one freshness rule: fresh, delayed, failed', () => {
    const now = new Date(Date.UTC(2026, 9, 31, 11, 30));
    const at = h => new Date(now - h * 3600000);
    const ok = { job: 'etl', status: 'success', run_timestamp: at(5).toISOString() };
    assert.equal(freshness(at(1), ok, now).state, 'fresh');
    const late = freshness(at(5.5), ok, now);
    assert.equal(late.state, 'delayed');
    assert.match(late.message, /5 hours old/);
    assert.equal(freshness(at(13), ok, now).state, 'failed');
    assert.equal(freshness(at(1), { ...ok, status: 'failure' }, now).state, 'failed');
    // The Pipeline card uses the same rule, so it can't say "Running normally" while the banner says delayed.
    const card = pipelineStatus([ok], now, at(5.5)).etl;
    assert.equal(card.state, 'warning');
    assert.equal(card.label, 'Delayed');
    assert.equal(pipelineStatus([ok], now, at(0.5)).etl.label, 'Up to date');
});

test('the headline compares with the 30-day average, and gives the rating', () => {
    const now = new Date(Date.UTC(2026, 8, 25, 12, 20));
    const summary = summarise([row(12, 197, { intensity_index: 'high' })], [{ day: '2026-09-20', intensity: 113, hours: 24 }], now);
    assert.equal(Math.round(summary.vsAverage), 74);
    assert.equal(summary.band.label, 'High');
});

test('the forecast summary says in words how the model compares with the simple forecast', () => {
    assert.match(skillSummary([{ metric: 'Overall_Intensity', skill: 0.21 }]), /beats .* by about 21%/);
    assert.match(skillSummary([{ metric: 'Overall_Intensity', skill: -0.1 }]), /worse .* about 10% larger/);
    assert.equal(skillSummary([]), '');
});

test('coal is its own fuel and the stack runs low carbon, imports, then fossil fuels', () => {
    assert.deepEqual(FUELS.map(f => f.key), ['wind', 'solar', 'nuclear', 'biomass', 'other', 'imports', 'coal', 'gas']);
    assert.equal(FUELS.find(f => f.key === 'other').label, 'Hydro and other');
});

test('the forecast, scheduled every 3 hours, is late after 4½ hours and failed after a day', () => {
    const now = new Date(Date.UTC(2026, 9, 31, 12));
    const run = (h, status = 'success') => ({ job: 'forecast', status, run_timestamp: new Date(now - h * 3600000).toISOString() });
    assert.equal(forecastStatus(run(3), now).state, 'good');
    assert.equal(forecastStatus(run(6), now).label, 'Late: no run for 6 hours');
    assert.equal(forecastStatus(run(25), now).state, 'critical');
    assert.equal(forecastStatus(run(1, 'failure'), now).state, 'critical');
    assert.equal(forecastStatus(null, now).state, 'unknown');
});
