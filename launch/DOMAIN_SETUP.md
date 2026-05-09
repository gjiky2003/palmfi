# PalmFi — Domain & HTTPS Setup Guide

## Option 1: Stay on ngrok (Recommended for Pilot)

ngrok is fine for the first 10-50 pilot loans. Your permanent domain `palm.ngrok.app`
already has auto-HTTPS. Zero setup cost, zero maintenance.

**When to upgrade:** Once you have your Texas license and are ready for
non-friend/family borrowers.

## Option 2: Custom Domain on DigitalOcean / VPS (Cheapest)

### Step 1 — Buy Domain
- **palmfi.com** — $10-15/yr at Namecheap, Cloudflare Registrar, or Porkbun
- Also check: **getpalmfi.com**, **trypalmfi.com**, **palmfi.loans**

### Step 2 — Set Up DNS
Using **Cloudflare** (free plan — also gives DDoS protection):

```
Record Type | Name        | Value
A           | @           | <your-server-ip>
CNAME       | www         | palmfi.com
```

### Step 3 — Configure Flask Server

In `app.py`, add the production host:

```python
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8085, debug=False)  # debug=False in prod
```

### Step 4 — Reverse Proxy with Nginx

```nginx
server {
    listen 80;
    server_name palmfi.com www.palmfi.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name palmfi.com www.palmfi.com;

    ssl_certificate /etc/letsencrypt/live/palmfi.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/palmfi.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8085;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Step 5 — SSL via Let's Encrypt

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d palmfi.com -d www.palmfi.com

# Auto-renew (certbot sets this up automatically)
sudo certbot renew --dry-run
```

## Option 3: Deploy to Cloudflare Workers (Next.js style)

If you want to move off ngrok to a VPS but don't want to manage Nginx:

1. Get a Cloudflare account (you already have one for efloral.net)
2. Set up Cloudflare Tunnel (cloudflared):
```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create palmfi
cloudflared tunnel route dns palmfi palmfi.com

# Run tunnel (add to startup script)
cloudflared tunnel run palmfi
```

3. Cloudflare Tunnel = no open ports, no Nginx, no cert management

## Update Settings After Domain Setup

Once your domain is live, go to `/admin/settings` and update:
- **Domain URL:** `https://palmfi.com`
- **Stripe Webhook Path:** `/stripe/webhook`

Then re-run the Stripe webhook configuration to point at your real domain.

## Checklist
- [ ] Buy domain (palmfi.com or similar)
- [ ] Point DNS to server (or set up Cloudflare Tunnel)
- [ ] Install Nginx + Let's Encrypt SSL / Cloudflare Tunnel
- [ ] Set `debug=False` in app.py
- [ ] Update Stripe webhook endpoint in Stripe Dashboard
- [ ] Update settings.json via /admin/settings
- [ ] Run E2E test to verify HTTPS works end-to-end
