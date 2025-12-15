# GitHub Actions Setup Guide

## Deploy to GitHub in 2 Minutes

### Step 1: Push Code to GitHub
```bash
git add .
git commit -m "Add Grid ETL pipeline"
git push origin main
```

The workflow file `.github/workflows/etl.yml` is already included!

### Step 2: Add DATABASE_URL Secret

1. Go to your GitHub repository
2. Click: **Settings** (top menu)
3. Left sidebar: **Secrets and variables** → **Actions**
4. Click: **New repository secret**
5. Fill in:
   - **Name:** `DATABASE_URL`
   - **Value:** `postgresql://user:pass@host:port/dbname`
6. Click: **Add secret**

That's it! ✅

---

## Monitor Your Pipeline

### View All Runs
1. Repository → **Actions** tab
2. See: "Grid ETL Pipeline" workflow
3. Click to see run history with timestamps and status

### View Run Details
1. Click any run
2. See:
   - Start time
   - End time  
   - Duration
   - Full log output
   - Artifacts (log files if failed)

### Manual Trigger
1. Actions tab
2. Select: "Grid ETL Pipeline"
3. Click: **Run workflow**
4. Select branch: `main`
5. Click: **Run workflow**

---

## What's Included

### Schedule
- **Frequency:** Every hour at :00 (UTC)
- **Example:** 00:00, 01:00, 02:00, ... 23:00 UTC daily

### Workflow Steps
1. Check out code
2. Set up Python 3.9
3. Cache pip dependencies (faster runs)
4. Install `requirements.txt`
5. Run `python etl_job.py`
6. Inject `DATABASE_URL` from secrets
7. Upload logs on failure (30-day retention)

### Runtime
- ~30-60 seconds per run
- Very lightweight (no heavy dependencies)

---

## Monitoring SQL Queries

Check your database for runs:

```sql
-- Total runs
SELECT COUNT(*) FROM etl_runs;

-- Success rate
SELECT 
  status,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM etl_runs), 1) as pct
FROM etl_runs
GROUP BY status;

-- Recent runs
SELECT run_timestamp, status, rows_inserted, execution_time_ms
FROM etl_runs
ORDER BY run_timestamp DESC
LIMIT 10;

-- Hourly execution time trend
SELECT 
  DATE_TRUNC('day', run_timestamp) as day,
  AVG(execution_time_ms) as avg_ms,
  MAX(execution_time_ms) as max_ms
FROM etl_runs
WHERE status = 'success'
GROUP BY 1
ORDER BY 1 DESC;
```

---

## Troubleshooting

### Workflow Not Running
- **Check:** Actions tab shows no runs
- **Fix 1:** Confirm workflow file exists: `.github/workflows/etl.yml` ✓
- **Fix 2:** Wait until top of next hour (:00 UTC)
- **Fix 3:** Manually trigger: Actions → "Run workflow"

### Workflow Failed ❌
- **Check:** Click failed run in Actions tab
- **Look for:**
  - `DATABASE_URL` secret not set → Set it in Settings
  - API connection error → Usually retries automatically
  - Import errors → Check Python version (3.9+)
- **Logs:** Full execution log visible in run details

### Database Not Getting Data
- **Check 1:** View failed run logs in Actions
- **Check 2:** Query database: `SELECT COUNT(*) FROM grid_telemetry;`
- **Check 3:** Verify `DATABASE_URL` is correct: `psql "$DATABASE_URL"`
- **Check 4:** Test locally: `python etl_job.py`

### Log Files Not Available
- **Check:** Failed run → Click "etl-logs" artifact
- **Note:** Only created on failure, retained 30 days

---

## Free Tier Limits

| Metric | Limit | Your Usage | Status |
|--------|-------|-----------|--------|
| Minutes/month | 2,000 | ~360 (18%) | ✅ Well under |
| Concurrent jobs | 20 | 1 | ✅ OK |
| Log retention | 90 days | 30 days set | ✅ OK |
| Storage | 500 MB | ~1-5 MB/month | ✅ OK |

**Bottom line:** You'll never hit limits with hourly runs. ✅

---

## Cost: $0 Forever ✅

- Free for public repositories
- 2,000 free minutes/month per account
- Your hourly pipeline uses ~18% of quota

---

## Best Practices

1. **Monitor regularly**
   - Check Actions tab weekly
   - Review `etl_runs` table for trends

2. **Archive old logs**
   - Keep last 30 days in GitHub
   - Keep last 6-12 months in database

3. **Test locally first**
   ```bash
   python etl_job.py
   tail etl_pipeline.log
   ```

4. **Update secrets if password changes**
   - Settings → Secrets → DATABASE_URL → Update

5. **Review logs for warnings**
   - Look for "WARNING" in logs
   - Check `etl_runs.error_message` for issues

---

## Next Steps

1. ✅ Push code to GitHub
2. ✅ Set DATABASE_URL secret
3. ✅ Wait for next hour (:00 UTC)
4. ✅ Check Actions tab for first run
5. ✅ Query database to confirm data
6. ✅ Set up Looker dashboard

**Your free hourly pipeline is ready!** 🚀
