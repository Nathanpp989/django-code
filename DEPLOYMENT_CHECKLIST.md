# Deployment Checklist

**Project:** Django LLM with FastAPI and NGINX  
**Last Updated:** May 2, 2026

---

## Pre-Deployment: 48 Hours Before

### Code Quality
- [ ] All tests passing: `pytest newDjango/ -v --cov`
- [ ] Code lint clean: `flake8 newDjango/ --exclude=migrations`
- [ ] Type hints checked: `mypy newDjango/` (if configured)
- [ ] No hardcoded secrets in codebase: `grep -r "password\|SECRET\|token" newDjango/ --exclude-dir=.git`

### Security
- [ ] Django security check: `python manage.py check --deploy`
- [ ] OWASP Top 10 review completed
- [ ] SQL injection risks reviewed (all ORM usage)
- [ ] Authentication flows verified
- [ ] Authorization checks verified on protected endpoints

### Database
- [ ] All migrations created and tested: `python manage.py makemigrations --check`
- [ ] Migrations tested on staging: `python manage.py migrate --plan` reviewed
- [ ] Database backed up: `pg_dump $DATABASE_URL > backup_predeployment_$(date +%Y%m%d).sql`
- [ ] Database indices verified: `SELECT * FROM pg_stat_user_indexes;`

### Environment
- [ ] `.env` file NOT committed to git
- [ ] All required environment variables documented
- [ ] Secrets stored in secure vault (Secrets Manager, Vault, etc.)
- [ ] Staging environment matches production configuration

---

## Pre-Deployment: 24 Hours Before

### NGINX & Infrastructure
- [ ] NGINX config syntax valid: `sudo nginx -t -c /path/to/newsite/nginx.conf`
- [ ] SSL certificates valid and non-expired: `openssl x509 -in /etc/nginx/ssl/server.crt -text -noout`
- [ ] SSL certificate chain complete
- [ ] Client certificates generated (if using mTLS on port 8443)
- [ ] NGINX configuration tested on staging server
- [ ] Firewall rules verified (ports 80, 443, 8443 accessible, 8000/8001 internal-only)

### Services
- [ ] Docker images built and tagged: `docker build -t django-llm:latest .`
- [ ] Docker image scanned for vulnerabilities: `docker scan django-llm:latest`
- [ ] Docker image runs locally: `docker run -it django-llm:latest bash`
- [ ] All required services documented (Redis, PostgreSQL, Ollama versions)
- [ ] Service health checks configured in monitoring

### Monitoring & Logging
- [ ] Sentry project created and configured
- [ ] Log aggregation configured (CloudWatch, DataDog, etc.)
- [ ] Alert rules configured for:
  - HTTP 5xx errors (> 5 in 5 minutes)
  - Brute force lockouts (> 10 in 10 minutes)
  - Slow queries (> 1 second)
  - Database connection errors
  - NGINX upstream failures
  - Disk space warnings (< 10% free)
- [ ] On-call rotation verified

---

## Pre-Deployment: 4 Hours Before

### Final Verification
- [ ] Health checks all passing on staging: `curl https://staging-app:8443/health`
- [ ] API endpoints responding on staging: `curl -H "Authorization: Bearer $TEST_TOKEN" https://staging-app:8443/api/health`
- [ ] Database connectivity confirmed
- [ ] Redis connectivity confirmed (if used)
- [ ] Ollama service responding (if required)
- [ ] NGINX responding correctly: `curl http://localhost` → redirect to HTTPS

### Backups & Rollback
- [ ] Full database backup completed
- [ ] Application code tagged in git: `git tag deployment-$(date +%Y%m%d-%H%M%S)`
- [ ] Previous version available for rollback
- [ ] Rollback procedure documented and tested

---

## Deployment: Execution

### Pre-Execution (5 min before)
- [ ] Team notified in Slack #deployments
- [ ] Runbook open and reviewed
- [ ] Emergency rollback procedure reviewed
- [ ] On-call engineer standing by

### Step 1: Database Migrations (if any)
```bash
# On deployment server
python manage.py migrate --no-input
# Expected output: "Operations to perform: X migration(s)"
```
- [ ] Migrations completed successfully
- [ ] No rollback database errors
- [ ] Verify migrations in database: `SELECT * FROM django_migrations;`

### Step 2: Static Files
```bash
python manage.py collectstatic --no-input
```
- [ ] Static files collected
- [ ] NGINX can serve from `/staticfiles/`

### Step 3: Deploy Application
```bash
# Stop old Gunicorn/FastAPI workers
sudo systemctl stop gunicorn
sudo systemctl stop fastapi

# Deploy new code (git pull, Docker pull, etc.)
git pull origin main
# OR
docker pull my-registry/django-llm:latest

# Start new services
sudo systemctl start gunicorn
sudo systemctl start fastapi

# Verify services started
sudo systemctl status gunicorn
sudo systemctl status fastapi
```
- [ ] Django/Gunicorn started successfully
- [ ] FastAPI started successfully
- [ ] No error logs in initial startup

### Step 4: Verify Health
```bash
# Health checks
curl https://localhost:8443/health
curl https://localhost:8443/api/health
curl https://localhost:8443/api/metrics

# Check logs for errors
sudo journalctl -u gunicorn -n 50
sudo journalctl -u fastapi -n 50
```
- [ ] All health checks passing
- [ ] No critical errors in logs
- [ ] Response times within expected range
- [ ] Database queries executing

### Step 5: Smoke Tests
- [ ] Can log in via web interface
- [ ] Can call authenticated FastAPI endpoints
- [ ] Chat functionality works
- [ ] Export functionality works
- [ ] Admin panel accessible
- [ ] Static assets loading

---

## Post-Deployment: Monitoring

### Immediate (0-5 minutes)
- [ ] Error rate normal
- [ ] Response times normal
- [ ] No spike in CPU/memory
- [ ] Database connections stable
- [ ] Logs clean (no exceptions)

### Short-term (5-30 minutes)
- [ ] All critical features tested
- [ ] No user reports of issues
- [ ] Brute force detector not triggering
- [ ] Rate limiter not blocking legitimate traffic
- [ ] Cache working (check metrics)

### Medium-term (30 minutes - 2 hours)
- [ ] Performance metrics stable
- [ ] No memory leaks detected
- [ ] Database queries performing as expected
- [ ] Logging/audit trails recording correctly

---

## Rollback Procedure (if needed)

```bash
# If deployment failed, execute immediately:

# 1. Stop new services
sudo systemctl stop gunicorn fastapi

# 2. Checkout previous code
git checkout <previous-tag>
# OR
docker pull my-registry/django-llm:<previous-tag>

# 3. Rollback database (if migrations caused issues)
python manage.py migrate <previous-migration-name>

# 4. Restart services
sudo systemctl start gunicorn fastapi

# 5. Verify
curl https://localhost:8443/health
sudo journalctl -u gunicorn -n 50
sudo journalctl -u fastapi -n 50

# 6. Notify team
# Message Slack #deployments: "Rollback completed to [previous-tag]"
```

---

## Post-Deployment: 24 Hours

### Stability Verification
- [ ] No critical errors reported
- [ ] Performance metrics stable
- [ ] All monitoring alerts in healthy state
- [ ] Database growth normal
- [ ] Log volume normal

### Documentation Update
- [ ] Deployment notes added to runbook
- [ ] Any issues encountered documented
- [ ] Fixes for future deployments documented
- [ ] This checklist updated if needed

---

## Deviations from Plan

If anything deviates from this checklist, **DO NOT PROCEED** without team approval.

Document any deviations:

| Step | Expected | Actual | Decision | Approved By |
|------|----------|--------|----------|-------------|
|      |          |        |          |             |

---

## Contacts & Escalation

- **Deployment Lead:** [NAME]
- **On-Call Engineer:** [NAME]
- **Database Admin:** [NAME]
- **Security Team:** [EMAIL]
- **Emergency Contact:** [PHONE]

---

## Post-Deployment Retrospective

**Date:** [DEPLOYMENT_DATE]  
**Status:** ✅ Success / ⚠️ Partial / ❌ Failed

### What Went Well
- [ ] ...

### What Could Be Improved
- [ ] ...

### Action Items for Next Deployment
- [ ] ...

---

**Deployment Completed:** [DATE/TIME]  
**Deployed By:** [USERNAME]  
**Reviewed By:** [USERNAME]
