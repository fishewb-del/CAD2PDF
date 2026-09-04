# Putting CAD2PDF on Google Cloud Run (the click-by-click version)

This is the guide to follow if drawings are too big for a free 512 MB
instance. It assumes you have never used Google Cloud. You will end up with
a web address you can send to anyone in the office, on a machine big enough
for real site drawings.

**Time:** about 30 minutes, most of it waiting for the first build.
**Cost:** $0 for normal use, but a credit card must be on file. See Step 3.
**What you need:** a Google account and a credit or debit card.

---

## Why this instead of Render's free plan

A real cross dock drawing was measured through this converter: it needed
**914 MB of memory and 88 seconds of full-speed CPU**. A free 512 MB
instance with a tenth of a CPU cannot do that twice over. It runs out of
memory, the server is killed mid-request, and the browser is left spinning.

Cloud Run gives this app **2 GB and a full CPU**. The same drawing converts
in about 96 seconds, start to finish, including reading the DWG.

| | Render free | Cloud Run (this guide) |
|---|---|---|
| Memory | 512 MB | 2 GB |
| CPU | 0.1 | 1 |
| Max upload | 16 MB | 32 MB |
| Request limit | 120 s | 300 s |
| That drawing | out of memory | 96 seconds |

---

## Before you start: two things to know

1. **A card is required, even though you will not be charged.** Google will
   not switch on Cloud Run without billing enabled. Inside the free monthly
   allowance the bill is $0. Step 3 explains the numbers and Step 11 sets up
   an alarm so you find out long before any charge could happen.
2. **The first conversion after a quiet spell is slow.** Nothing runs while
   nobody is converting, which is why it is free. Waking up takes 30 to 60
   seconds because the image is large. After that it is quick until the next
   idle spell.

---

## Step 1. Create a Google Cloud account

1. Go to <https://console.cloud.google.com>.
2. Sign in with a Google account. A personal Gmail is fine; a work Google
   Workspace account is also fine.
3. If it offers a "free trial with $300 credit", you can accept or skip it.
   It makes no difference to this guide. The allowance this app runs inside
   is the permanent free tier, not the trial credit.

---

## Step 2. Create a project

A project is just a labelled box that holds the app and its bill.

1. At the very top of the page, next to "Google Cloud", click the project
   dropdown. It might say "Select a project".
2. Click **New project**.
3. **Project name:** `cad2pdf`. Leave the organisation as it is.
4. Click **Create** and wait about ten seconds.
5. Click the dropdown again and select **cad2pdf** so it is the active
   project. The name should now show at the top of every page.

Write down the **Project ID**. It is on the dashboard and usually looks like
`cad2pdf-473915`, with numbers on the end. It is not the same as the name.

---

## Step 3. Turn on billing

1. Open the menu (three lines, top left) and choose **Billing**.
2. Click **Link a billing account**, then **Create billing account**.
3. Enter your details and card. Google places a small temporary
   authorisation to check the card is real, then releases it.
4. Back on the Billing page, confirm the `cad2pdf` project is linked.

**What you are actually agreeing to.** Cloud Run's permanent free tier
includes roughly 180,000 vCPU-seconds and 360,000 GB-seconds of memory per
month, plus 2 million requests. Converting that cross dock drawing uses
about 96 vCPU-seconds and 192 GB-seconds. That is roughly **1,800
conversions of a large drawing per month, free**. You would have to convert
60 heavy drawings a day, every day, to reach a bill.

Allowances change. Current figures: <https://cloud.google.com/run/pricing>

Step 11 sets a spending alert regardless, so you are never surprised.

---

## Step 4. Open Cloud Shell

Cloud Shell is a terminal that runs inside the browser. Nothing to install.

1. At the top right of the console, click the **`>_`** icon
   ("Activate Cloud Shell").
2. A black panel opens along the bottom. First time, it asks to continue.
   Click **Continue** and wait for a prompt to appear.

If it asks you to authorise, click **Authorize**.

---

## Step 5. Get the code

Copy and paste this into Cloud Shell, then press Enter:

```bash
git clone https://github.com/fishewb-del/CAD2PDF.git
cd CAD2PDF
```

Now check that the Cloud Run files are actually there:

```bash
ls deploy/cloudrun.sh
```

**If that says `No such file or directory`,** the Cloud Run support has not
been merged into the default branch yet. Switch to the branch carrying it:

```bash
git checkout claude/pdf-cad-dxf-error-dgxwsh
ls deploy/cloudrun.sh
```

The second `ls` should print the path back to you. Everything below works
the same either way. (Once that branch is merged, a plain clone is enough
and this step can be skipped.)

If the clone asks for a GitHub login, the repository is private. Either make
it public in the repo's **Settings → General → Danger Zone → Change
visibility**, or generate a personal access token on GitHub and use that as
the password.

---

## Step 6. Deploy

Two commands. Replace `YOUR_PROJECT_ID` with the Project ID from Step 2.

```bash
gcloud config set project YOUR_PROJECT_ID
./deploy/cloudrun.sh
```

The script switches on the services it needs, then builds and deploys.

**The first build takes 10 to 15 minutes.** It compiles LibreDWG from source
so that `.dwg` files work without converting them by hand first. Later
deploys are much quicker. It is normal for the screen to sit quiet for
minutes at a time.

If it asks to enable an API, answer `y`. If it asks for a region and the
script did not supply one, choose `us-central1`.

When it finishes it prints your web address, ending in `.run.app`.

---

## Step 7. Open it

Paste the printed address into a browser tab. You should get the CAD2PDF
upload page, with **ARCH D** already selected as the sheet size.

**The address is public.** Anyone who has it can use it. Step 9 puts a
password on it, which matters because this handles client drawings.

---

## Step 8. Prove it actually works

Upload the drawing that was failing before. Watch for three things:

1. The **preview** appears, showing the drawing itself.
2. **Convert to PDF** returns a file rather than spinning.
3. The PDF opens, and the scale in the footer reads correctly.

A large site drawing takes 90 seconds or so. The button says "Still
converting, this is a big drawing" while it works, so you know it is alive.

If a drawing is genuinely too big even for this, the app now says so in
plain English instead of hanging. That message names what ran out.

---

## Step 9. Put a password on it

Run this in Cloud Shell, with a password of your choosing:

```bash
gcloud run services update cad2pdf --region us-central1 \
    --update-env-vars CAD2PDF_USERNAME=edger,CAD2PDF_PASSWORD=pick-something-good
```

Wait about 30 seconds, then reload the page. The browser now asks for the
username and password before showing anything.

The health check stays open on purpose, so Google can still see the app is
running.

To change it later, run the same command with a new password. To remove it:

```bash
gcloud run services update cad2pdf --region us-central1 \
    --remove-env-vars CAD2PDF_USERNAME,CAD2PDF_PASSWORD
```

---

## Step 10. Check what the server thinks it has

Visit `/status` on your address, for example
`https://cad2pdf-xxxxx.run.app/status`.

It reports the memory it is allowed, the time limits, whether DWG support
made it into the build, whether fonts are present, and which commit is
running. When something behaves oddly, this page is the first place to look.

The numbers to expect from this guide: memory budget around 1500 MB, convert
timeout 240 seconds, DWG support **yes**, fonts **available**.

---

## Step 11. Keep the bill at zero

**Set a budget alert.** This is the important one.

1. Menu → **Billing** → **Budgets & alerts** → **Create budget**.
2. Name it `cad2pdf`, scope it to the `cad2pdf` project.
3. Set the target amount to **$1**.
4. Leave the default alert thresholds. Click **Finish**.

You will now get an email if the app ever costs even a dollar, which under
normal use it will not.

**The other guard is already set.** The deploy script caps the service at 3
instances, so nothing can quietly scale up and run a bill. To see what you
have used: Menu → **Billing** → **Reports**.

---

## Step 12. Day to day

**Deploying a change.** After code changes are pushed to GitHub:

```bash
cd ~/CAD2PDF && git pull && ./deploy/cloudrun.sh
```

If you had to switch branches in Step 5, `git pull` follows that same
branch, which is what you want.

**Changing the sizing.** Edit `deploy/cloudrun.env.yaml` for app settings
(upload limit, timeouts, default sheet size), or set the variables at the
top of `deploy/cloudrun.sh` for machine settings. For example, to give it
4 GB:

```bash
MEMORY=4Gi ./deploy/cloudrun.sh
```

Bear in mind that doubling memory halves how many conversions fit in the
free allowance.

**Reading the logs.** Menu → **Cloud Run** → **cad2pdf** → **Logs**.

---

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `./deploy/cloudrun.sh: No such file or directory` | You are on a branch without the Cloud Run files | `git checkout claude/pdf-cad-dxf-error-dgxwsh`, see Step 5 |
| `PERMISSION_DENIED` enabling services | Billing is not linked yet | Redo Step 3, confirm the project is linked |
| Build fails on LibreDWG | Usually a transient download failure | Run `./deploy/cloudrun.sh` again |
| `Cloud Build has not been used...` | The API needs a moment after enabling | Wait 60 seconds and re-run the script |
| Page asks for a Google login | The service was deployed private | Re-run the script; it passes `--allow-unauthenticated` |
| First request takes a minute | Cold start, the app was asleep | Normal. Set `MIN_INSTANCES=1` to avoid it, but that is no longer free |
| "needs more memory than this server has" | The drawing really is too big for 2 GB | `MEMORY=4Gi ./deploy/cloudrun.sh` |
| Conversion works but the sheet looks empty | Model space is spread over a huge area | Set an explicit scale rather than auto-fit |

---

## What this actually set up

- A Cloud Run service called **cad2pdf** in **us-central1**, built from the
  repository's own Dockerfile, so DWG support is compiled in.
- **2 GB of memory and one full vCPU**, handling **one drawing at a time**.
  That last part matters: Cloud Run's default is 80 requests per instance,
  and 80 conversions sharing 2 GB would run it out of memory. Instead Cloud
  Run starts more instances, up to 3.
- **Scale to zero**, so nothing is billed while nobody is converting.
- Time limits that nest properly: the app stops its own work at 240 seconds,
  gunicorn at 300, Cloud Run at 300. The app is always the one that answers,
  so you get a readable message instead of a dead connection.
- Uploads capped at 32 MB, twice what the 512 MB free tier allowed.
