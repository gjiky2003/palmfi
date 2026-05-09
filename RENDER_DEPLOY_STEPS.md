# PalmFi — Free Test Deploy on Render

You signed up on Render. Here's the rest. **Total: ~10 minutes.**

---

## Step 1 — Push Code to GitHub (5 min)

Render deploys from a GitHub repo. You'll need one.

### 1a. Create empty GitHub repo

Go to https://github.com/new
- Name: `palmfi` (or anything)
- **Private** (it has admin password generation logic — keep it private)
- Don't initialize with README — we already have files
- Click **Create repository**

### 1b. Push from your machine

Copy the commands GitHub shows you, OR run these (replace `YOUR-USERNAME`):

```bash
cd ~/palmfi
git init
git add .
git commit -m "Initial PalmFi lending platform"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/palmfi.git
git push -u origin main
```

If you get an auth error, GitHub now requires a Personal Access Token instead of password:
- https://github.com/settings/tokens → Generate new token (classic) → check `repo` → use the token as your password when pushing.

---

## Step 2 — Deploy on Render (3 min)

### 2a. New Blueprint deploy (uses the `render.yaml` I already created)

1. Go to **https://dashboard.render.com**
2. Click **New +** → **Blueprint**
3. Click **Connect a repository** → authorize Render to access your GitHub → pick `palmfi`
4. Render will auto-detect `render.yaml` and show: "1 Web Service: palmfi"
5. Click **Apply**

### 2b. What happens

Render will:
- Install dependencies (`flask`, `bcrypt`, `gunicorn`, `PyJWT`, `python-dotenv`)
- Start the app via `gunicorn wsgi:app`
- Auto-generate `SECRET_KEY`, `JWT_SECRET`, and `ADMIN_PASSWORD`
- Give you a URL like `https://palmfi.onrender.com`
- Build takes ~3–5 minutes the first time

### 2c. Get your admin password

After deploy:
1. Render dashboard → your service → **Environment** tab
2. Copy the value of `ADMIN_PASSWORD` (it was auto-generated)
3. That's your login password for `/admin/login`

---

## Step 3 — Test It (2 min)

Visit your live URL: `https://palmfi.onrender.com`

✅ Try:
- Landing page loads
- Click "Get started" → register a test borrower
- Fill the 5-step application
- See decision page
- Logout → log back in
- Visit `/admin/login` with `admin@palmfi.com` + the password from Step 2c

---

## ⚠️ Free Tier Limits — Important

Render free tier:
- **App spins down after 15 min of inactivity** — first request after that takes ~30 seconds to wake up. Fine for testing, not for production.
- **No persistent disk** — SQLite database **resets on every redeploy**. Every `git push` wipes registered users, applications, loans. ✅ Fine for testing • ❌ Not fine for real loans.
- **No cron jobs** on free plan — autopilot won't run automatically. You can run it manually via Render's "Shell" tab.
- **750 free hours/month** across all services (one app uses ~744h).
- **HTTPS auto-included.**

When you're ready for real customers, upgrade to paid (~$7/mo Web + $7/mo for Postgres) and edit `render.yaml` to add a persistent disk.

---

## Step 4 — Connect Your Domain (Later, Optional)

When you buy `palmfi.com`:
1. Render dashboard → service → **Settings** → **Custom Domains** → add `palmfi.com`
2. Cloudflare DNS → add CNAME pointing to Render's URL
3. Render auto-provisions SSL

---

## What's Auto-Configured Already

| File | What it does |
|---|---|
| `render.yaml` | Blueprint config — Render reads this to auto-deploy |
| `Procfile` | Backup process spec (in case Render misses the yaml) |
| `runtime.txt` | Pins Python 3.11.9 |
| `requirements.txt` | Pip dependencies |
| `wsgi.py` | Gunicorn entrypoint loading the Flask app |
| `.gitignore` | Keeps secrets/DB out of git |

---

## Troubleshooting

**Build fails with "ModuleNotFoundError"** → check `requirements.txt` — paste the exact error and I'll fix.

**App boots but 502 Bad Gateway** → check Render logs for the actual Python error. Usually a missing env var.

**Login works but admin page 500s** → DB schema mismatch from autopilot migration. Run in Render Shell:
```bash
python scripts/migrate_autopilot.py
```

**Page loads but ugly (no styles)** → Tailwind is loaded from CDN, browsers may block. Check browser console.

---

## Tell me when it's deployed

Send me the Render URL and any error messages. I'll diagnose anything that breaks.
