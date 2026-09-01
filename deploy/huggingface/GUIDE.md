# Putting CAD→PDF online — the simple version

This gets your converter on the internet at its own web address, for free.
No credit card, no terminal, no installing anything. You'll copy and paste
two blocks of text into a website. Budget about 15 minutes, most of which
is waiting.

We're using **Hugging Face Spaces** — a free hosting service. (It's aimed at
AI projects, but it runs any app, and the free tier is generous.)

---

## Step 1 — Make a free account

1. Go to **<https://huggingface.co/join>**
2. Sign up with your email. Confirm the email they send you.

That's it. No payment details are requested.

---

## Step 2 — Create the Space

A "Space" is just their word for a hosted app.

1. Go to **<https://huggingface.co/new-space>**
2. Fill in:
   - **Space name:** `cad2pdf` (this becomes part of your web address)
   - **License:** leave as is
   - **Select the Space SDK:** click **Docker**, then choose **Blank**
   - **Space hardware:** leave on the free `CPU basic` option
   - **Visibility:**
     - **Private** → only you can use it. *Choose this for client drawings.*
     - **Public** → anyone with the link can use it.
3. Click **Create Space**.

You'll land on a page saying the Space is empty and needs files. Correct —
we'll add two.

---

## Step 3 — Add the first file (`Dockerfile`)

This file tells the server how to build the app.

1. Click the **Files** tab near the top of your Space's page.
2. Click **+ Add file** → **Create a new file**.
3. In the **Name your file** box, type exactly:

   ```
   Dockerfile
   ```

   (Capital D, no file extension.)

4. Into the big text box, paste the entire contents of
   [`deploy/huggingface/Dockerfile`](./Dockerfile) from the GitHub repo.

   To copy it: open the file on GitHub and click the **copy** icon at the
   top-right of the file view.

5. Scroll down and click **Commit new file to main**.

---

## Step 4 — Add the second file (`README.md`)

This one tells Hugging Face how to run the app.

1. **+ Add file** → **Create a new file** again.
2. Name it exactly:

   ```
   README.md
   ```

3. Paste this in, exactly as-is — **the `---` lines matter**:

   ```
   ---
   title: CAD to PDF
   emoji: 📐
   colorFrom: blue
   colorTo: gray
   sdk: docker
   app_port: 8000
   ---

   Converts DWG and DXF drawings to accurately scaled, true-vector PDFs.
   ```

4. Click **Commit new file to main**.

---

## Step 5 — Wait for it to build

The Space starts building itself immediately. At the top of the page you'll
see a status badge:

- **Building** (yellow) — normal. **This takes 5–10 minutes the first time**,
  because it compiles the DWG reader from source. Go make coffee.
- **Running** (green) — it's live.

You can click **Logs** to watch progress if you like.

If it goes red and says **Build error**, see Troubleshooting below.

---

## Step 6 — Use it

Once it says **Running**, your converter is live at:

```
https://<your-username>-cad2pdf.hf.space
```

You'll also see the app embedded directly on the Space page.

Drop in a `.dwg` or `.dxf`, pick a scale and paper size, hit **Convert to
PDF**, and download the result. Bookmark the address — that's your tool now.

---

## Sharing it

- **Private Space:** only you (signed in) can reach it. Best for client work.
- **Public Space:** anyone with the link can use it. There's no password on
  the app itself, so don't make it public if it'll handle confidential
  drawings.

To change this later: **Settings** tab → **Change visibility**.

---

## When your Space goes to sleep

Free Spaces pause after a stretch of no use. The first visit afterwards
takes ~30 seconds to wake up. Nothing is lost. This is normal.

---

## Updating it later

If the code on GitHub changes and you want your Space to pick it up:

**Settings** tab → scroll to **Factory rebuild** → click it.

A normal restart won't fetch new code — it reuses the cached build.
*Factory rebuild* is the one that re-pulls from GitHub.

---

## Troubleshooting

**"Build error" / red badge**
Click the **Logs** tab and read the last ~20 lines. The most common causes:

- The `Dockerfile` got pasted incompletely — check the last line is the
  `CMD [...]` block. Re-paste the whole file.
- The file is named `dockerfile` or `Dockerfile.txt` instead of `Dockerfile`.
  Rename it (open the file → pencil icon → rename).

**App loads but says "DWG support isn't installed"**
The DWG builder stage didn't make it into the image. Do a **Factory
rebuild**. If it persists, the Logs will show where the build stopped.

**"Configuration error" or the app doesn't appear on the page**
Almost always the `README.md` frontmatter. It must start on line 1 with
`---`, and include both `sdk: docker` and `app_port: 8000`.

**Uploads over 32 MB fail**
That's the built-in limit. To raise it, add this line to the Space's
README frontmatter is *not* enough — instead go to **Settings** →
**Variables and secrets** → **New variable**, name `CAD2PDF_MAX_UPLOAD_MB`,
value e.g. `64`, then **Factory rebuild**.

**A specific DWG won't convert**
Some unusual DWG revisions defeat the open-source reader. Open the drawing
in AutoCAD and do *Save As → DXF*, then upload that. DXF always works and
loses no accuracy.
