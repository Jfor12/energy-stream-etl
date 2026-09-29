import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    createClient, summarise, toSeries, intensityForecast, pipelineStatus, skillRows, niceTicks, dayString, mixAverages, FUELS,
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
