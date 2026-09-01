# Putting CAD2PDF online with Render (the click-by-click version)

This guide assumes you have never deployed anything. No terminal, no git
commands, no credit card. Follow it top to bottom and you will end up with
a web address you can send to anyone in the office, where they can drop in a
DWG or DXF and get back a properly scaled PDF.

**Time:** about 20 minutes, most of it waiting for the first build.
**Cost:** $0 on Render's free plan.
**What you need:** the GitHub account that owns this repository, and an email
address.

---

## Before you start: the two things to know about the free plan

1. **It falls asleep.** After about 15 minutes with nobody using it, Render
   shuts the app down to save resources. The next person to open the link
   waits roughly 30 to 60 seconds while it wakes up. Nothing is lost, it is
   just slow that one time. Step 9 shows how to avoid it.
2. **It is a small machine.** 512 MB of memory. That is plenty for a floor
   plan or a site plan. A 60 MB civil drawing with every utility layer turned
   on can run it out of memory. The upload limit is set to 16 MB for exactly
   this reason.

If the app becomes something the crew uses every day, Render's $7/month
Starter plan removes both limits. Step 11 covers the switch.

---

## Step 1. Make sure the code is on GitHub

It already is: <https://github.com/fishewb-del/CAD2PDF>

Open that link and confirm you can see the files. If GitHub asks you to log
in, log in with the account that owns the repo. That is the account Render
will connect to in the next step.

> **Note on the branch name.** This repo does not have a branch called
> `main`. Its default branch is called `claude/cad-to-pdf-converter-y9kc7s`.
> That is fine, Render will offer it to you and it works exactly the same.
> If you would rather it said `main`, go to the repo's
> **Settings → General → Default branch**, click the pencil icon, rename it,
> and use `main` everywhere below.

---

## Step 2. Create a Render account

1. Go to <https://render.com> and click **Get Started** (or **Sign In**).
2. Choose **GitHub** as the sign-in method. This is the important part: it
   links the two accounts in one shot, so Render can see your repositories.
3. GitHub will ask you to authorize Render. Click **Authorize Render**.
4. GitHub then asks **which** repositories Render may see. Pick either
   **All repositories** or **Only select repositories**. If you pick "only
   select", tick **CAD2PDF**. Click **Install**.
5. Render asks a couple of onboarding questions (name, what you are
   building). Answer anything. It does not affect the deployment.

You are now looking at the Render **Dashboard**. It is empty.

---

## Step 3. Point Render at the repository

The repo contains a file called `render.yaml` that already describes the
whole setup: what to build, how much memory, what environment variables. In
Render's language that file is a **Blueprint**. You do not have to configure
anything by hand.

1. In the Render dashboard, click **New** (top right) and choose
   **Blueprint**.
2. You see a list of your GitHub repositories. Find **CAD2PDF** and click
   **Connect**.
   - If it is not listed, click **Configure account** / **Reconfigure**,
     which takes you back to GitHub's permission screen from Step 2.4. Grant
     access to CAD2PDF and come back.
3. **Branch:** pick the branch you confirmed in Step 1
   (`claude/cad-to-pdf-converter-y9kc7s`, or `main` if you renamed it).
4. **Blueprint Name:** type anything. `cad2pdf` is fine.
5. Render reads `render.yaml` and shows you what it is about to create: one
   web service named **cad2pdf** on the **Free** plan.
6. Click **Apply** (or **Deploy Blueprint**).

### If the Blueprint screen gives you trouble

There is a manual path that produces the same result:

1. **New → Web Service**.
2. Connect the **CAD2PDF** repository, pick the branch.
3. **Language / Runtime:** choose **Docker**. Render should detect this on
   its own because there is a `Dockerfile` in the repo.
4. **Instance Type:** choose **Free**.
5. Leave everything else at its default and click
   **Create Web Service**.
6. Afterwards, open the **Environment** tab and add these, one at a time:

   | Key | Value |
   |---|---|
   | `WEB_CONCURRENCY` | `1` |
   | `WEB_THREADS` | `4` |
   | `CAD2PDF_MAX_UPLOAD_MB` | `16` |
   | `CAD2PDF_DWG_TIMEOUT` | `75` |
   | `GUNICORN_TIMEOUT` | `120` |
   | `CAD2PDF_DEFAULT_PAPER` | `ARCH D` |

   Click **Save Changes**. The service redeploys itself.

---

## Step 4. Wait for the first build

Render is now doing three things: downloading the code from GitHub, building
a container image from the `Dockerfile`, and starting it.

**The first build takes 8 to 15 minutes.** Most of that is compiling
LibreDWG, the open source library that reads Autodesk's DWG format. It is
slow, it only happens on builds that change the Dockerfile, and it is what
makes `.dwg` uploads work instead of forcing everyone to export DXF first.

Watch the **Logs** tab. You will see a wall of compiler output. What you are
waiting for at the end is:

```
==> Your service is live 🎉
```

The status chip at the top of the page turns green and reads **Live**.

If it goes red and says **Failed**, jump to the troubleshooting table at the
bottom.

---

## Step 5. Open your app

At the top of the service page there is a URL that looks like:

```
https://cad2pdf.onrender.com
```

(If someone already took `cad2pdf`, Render adds characters, for example
`cad2pdf-a1b2.onrender.com`. Use whatever it shows you.)

Click it. You should see the CAD to PDF page with a drop zone.

That link is your app. Bookmark it. Send it to whoever needs it.

---

## Step 6. Prove it actually works

1. Download a test drawing: on the GitHub repo, open
   `examples/sample-with-text.dxf` and click the **Download raw file**
   button (the download arrow, top right of the file view).
2. Back on your app, drag that file onto the drop zone.
3. **The drawing appears in a viewer.** Drag to pan, scroll to zoom,
   double-click to zoom in, **Fit** to reset. Zoom right in on the text: it
   stays sharp, because the preview is vector. This is the drawing itself,
   not the plotted sheet.
4. Leave **Paper size** on `ARCH D` and **Scale** on "Fit to page".
5. Click **Convert to PDF**, then **Download PDF**.
6. Open the PDF. The footer prints the scale it was drawn at. Print it at
   100 percent (not "fit to page") and a scale rule will read true off it.

Then try one of your own drawings. Start with a DXF if you have one, since
that path has the fewest moving parts.

---

## Step 7. Check the deployment dashboard

Your app has a built-in status page. Add `/status` to the end of your URL:

```
https://cad2pdf.onrender.com/status
```

It tells you, in plain language:

- which **GitHub commit** is running right now, as a clickable link back to
  GitHub
- whether **DWG support** made it into the build
- whether **fonts** are installed, which decides whether drawings
  containing text can be converted at all
- whether the **password gate** is on
- the upload limit and timeouts currently in force
- how long this instance has been awake (a small number usually just means
  it woke up, not that it crashed)

This is the page to look at when you push a change and are not sure whether
it went live. If the commit shown is not the one you just pushed, the deploy
either has not finished or it failed, and the **Events** tab in Render will
say which.

---

## Step 8. Put a password on it (strongly recommended)

Your Render URL is public. Anybody who has the link, or guesses it, can
upload drawings through it. Nothing is stored on the server, every
conversion happens in a temporary folder that is deleted the moment the
response is sent, but the app itself is open to the world. For client
drawings, close it:

1. In Render, open your **cad2pdf** service.
2. Click the **Environment** tab on the left.
3. Click **Add Environment Variable** twice and enter:

   | Key | Value |
   |---|---|
   | `CAD2PDF_USERNAME` | `edger` (or whatever you want) |
   | `CAD2PDF_PASSWORD` | a password you choose |

4. Click **Save Changes**. Render restarts the service, which takes a minute
   or two.

Now the site asks for that username and password in the browser's own
sign-in box before it will show anything. Everyone who needs it uses the same
pair. Change the password by editing that variable and saving again.

Two details worth knowing:

- `/healthz` stays open deliberately. That is the address Render itself
  checks to decide whether a deploy worked. If it required a password, every
  deploy would be marked failed.
- This is basic HTTP authentication. It is fine over the `https://` Render
  gives you. It is not a login system with separate accounts per person.

---

## Step 9. Auto-deploy, and keeping it awake

**Auto-deploy is already on.** Every time a change lands on the branch you
connected in Step 3, Render notices within seconds, rebuilds, and swaps the
new version in. You do not click anything. Confirm on `/status` that the
commit changed.

To turn that off, or to change which branch it watches: service →
**Settings** → **Build & Deploy**.

To deploy by hand at any time: the **Manual Deploy** button at the top right
of the service page. **Deploy latest commit** pulls whatever is currently on
the branch. **Clear build cache & deploy** does the same but rebuilds
LibreDWG from scratch, which is the thing to try when a build behaves
strangely.

**Keeping it awake.** If the 30 to 60 second wake-up is a problem, set up a
free uptime monitor (UptimeRobot, Better Stack, and others have free tiers)
to request your `/healthz` address every 10 minutes. Render sees the traffic
and never puts the app to sleep. Be aware this consumes your free instance
hours continuously, so keep it to this one service.

---

## Step 10. Day to day

| I want to... | Where to click |
|---|---|
| See if it is running | Service page, green **Live** chip |
| See which version is live | Your app's `/status` page |
| See what happened and when | **Events** tab |
| Read error output | **Logs** tab |
| Change a setting or password | **Environment** tab, then **Save Changes** |
| Force a rebuild | **Manual Deploy → Deploy latest commit** |
| Roll back a bad change | **Events** tab, find a good earlier deploy, **Rollback** |
| Use your own web address | **Settings → Custom Domains** |

---

## Step 11. When to spend the $7

Move to the **Starter** plan (service → **Settings** → **Instance Type** →
**Starter**) when any of these start to bite:

- The wake-up delay annoys people. Paid instances never sleep.
- Bigger drawings fail. Starter has 512 MB as well, but you can go up from
  there, and you can raise `CAD2PDF_MAX_UPLOAD_MB` alongside it.
- DWG conversions time out. Free gives you 0.1 of a CPU, which is genuinely
  slow for a large DWG. Paid CPU makes that go away.

After upgrading, raise the limits in the **Environment** tab:
`CAD2PDF_MAX_UPLOAD_MB` to `32` or `64`, `CAD2PDF_DWG_TIMEOUT` to `180`,
`GUNICORN_TIMEOUT` to `300`, and `WEB_CONCURRENCY` to `2` if you moved to an
instance with more than 512 MB.

---

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| Build fails compiling LibreDWG | Usually a network hiccup fetching the source | **Manual Deploy → Clear build cache & deploy** |
| Build succeeds, then **Deploy failed** with health check errors | The app started but `/healthz` did not answer in time | Check **Logs** for a Python error. Confirm `CAD2PDF_PASSWORD` was not applied to the health check (it is exempt by design) |
| First visit of the day takes 40 seconds | Free plan sleep, working as designed | Nothing, or see Step 9 |
| Page loads but converting spins forever, then errors | Drawing too big for a 512 MB instance | Try a smaller drawing, or upgrade per Step 11 |
| "That file is larger than the 16 MB upload limit" | The upload cap | Purge unused layers and re-save, or raise `CAD2PDF_MAX_UPLOAD_MB` |
| "This DWG file took too long to convert" | 0.1 CPU is too slow for that file | Export DXF from your CAD program and upload that, or upgrade |
| "This DWG file could not be read" | An unusual or very new DWG revision | In your CAD program, **Save As → DXF**, upload the DXF. Scale is preserved |
| `/status` shows **DWG conversion: not available** | The image was built without LibreDWG | Confirm the service runtime is **Docker**, not Python, then rebuild |
| "no fonts available, not even fallback fonts" | The server has no fonts, so text cannot be drawn | Fixed in the image. If you see it, you are on an old build: **Manual Deploy → Clear build cache & deploy**, then check `/status` says text rendering is available |
| The drawing preview never appears | The preview call failed; converting may still work | Try converting anyway. If a very large drawing, the free instance may have run out of memory, see Step 11 |
| `/status` shows an old commit | The deploy has not finished, or failed | **Events** tab tells you which |
| Repository not listed when connecting | Render was not granted access to it | **Configure account** on the connect screen, tick CAD2PDF on GitHub |

---

## What this actually set up

For the record, in case someone technical asks later:

- Render builds the repo's `Dockerfile`, which compiles LibreDWG's `dwg2dxf`
  in one stage and then installs Python, Flask, ezdxf and matplotlib in
  another.
- The container runs `gunicorn` with 1 worker and 4 threads, because 2
  workers each holding a rendered drawing will exhaust a 512 MB instance.
- `render.yaml` holds the whole configuration, so the setup is reproducible
  and reviewable rather than a pile of clicks somebody has to remember.
- Uploaded drawings are never written to persistent storage. Each conversion
  runs in a temporary directory that is deleted when the response is sent.
- Other deployment options (Fly.io, any plain Docker host) are in
  [DEPLOY.md](DEPLOY.md).
