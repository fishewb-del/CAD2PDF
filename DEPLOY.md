# Deploying cad2pdf

The app needs a real server: it runs Python (ezdxf + matplotlib) and shells
out to the LibreDWG `dwg2dxf` binary for `.dwg` files. That rules out static
hosts like GitHub Pages. Every option below builds the `Dockerfile`, so DWG
support comes along with it.

## Option 1 — Hugging Face Spaces (free, no credit card)

> **Non-technical? Follow [deploy/huggingface/GUIDE.md](deploy/huggingface/GUIDE.md)
> instead** — a click-by-click walkthrough that needs no terminal and no git.
> The steps below are the shorter version for people comfortable with a shell.

Free CPU Spaces get 2 vCPU / 16 GB RAM, which is plenty, and they don't ask
for a card. Spaces sleep after a long idle period and wake on the next
request.

1. Sign up at <https://huggingface.co>, then **New → Space**.
2. Name it, choose **Docker → Blank**, visibility **Public** (free tier).
3. Clone the Space and copy this project into it:

   ```bash
   git clone https://huggingface.co/spaces/<you>/<space-name>
   cd <space-name>
   # copy the project in (everything except .git)
   rsync -av --exclude '.git' /path/to/CAD2PDF/ .
   # the Space needs its own README with the config frontmatter:
   cp deploy/huggingface/README.md README.md
   git add -A && git commit -m "Deploy cad2pdf" && git push
   ```

4. The Space builds the image (first build takes a few minutes because it
   compiles LibreDWG) and serves at
   `https://<you>-<space-name>.hf.space`.

`app_port: 8000` in that README must match the container's port. If you
change the port, change both.

**Note:** a public Space is publicly usable — anyone with the link can
upload. Use a private Space, or add auth, for client drawings.

## Option 2 — Render (free tier)

`render.yaml` is a blueprint, so there's nothing to configure:

1. <https://render.com> → **New → Blueprint**
2. Connect this repo, pick the branch, **Apply**.
3. You get `https://<name>.onrender.com`.

Free instances sleep after ~15 minutes idle; the next request takes ~30–50s
to wake. Change `plan: starter` in `render.yaml` to `free` if you want the
free tier explicitly.

## Option 3 — Fly.io

`fly.toml` is ready. Requires the `flyctl` CLI and a card on file (there is
a small free allowance).

```bash
fly launch --copy-config --now
fly open
```

## Anything else

Any Docker host works — Railway, Cloud Run, a VPS:

```bash
docker build -t cad2pdf .
docker run -d -p 8000:8000 cad2pdf
```

## Locking it down

The app has no authentication: anyone with the URL can convert files. Before
sharing a link that will handle client drawings, either keep the deployment
private (private HF Space, internal VPS) or put auth in front of it. Uploads
themselves are never persisted — each conversion happens in a temp directory
that is deleted when the response is sent.

## Environment variables

| Var | Purpose | Default |
|---|---|---|
| `PORT` | Port to listen on | `8000` |
| `CAD2PDF_MAX_UPLOAD_MB` | Upload size limit | `32` |
| `CAD2PDF_DWG2DXF` | Path to the `dwg2dxf` binary | `dwg2dxf` on `PATH` |
| `CAD2PDF_DWG_TIMEOUT` | Max seconds for a DWG→DXF conversion | `120` |
