# Stage 3 Migration from the Stage 1–2 Project

If your current project already has working Stage 1 and Stage 2 data, you do not need to delete it.

## 1. Stop the development servers

Backend: press `Ctrl+C` in the Uvicorn terminal.

Frontend: press `Ctrl+C` in the Vite terminal.

## 2. Back up the current project

From `~/ragProject`:

```bash
cd ~
cp -a ragProject ragProject_stage2_backup
```

## 3. Replace/add Stage 3 application files

Copy the contents of this package over your existing `~/ragProject` while preserving your existing `backend/data/raw/` and `backend/data/metadata/` files.

Create the new extraction storage directory if needed:

```bash
mkdir -p ~/ragProject/backend/data/extracted
```

Existing Stage 1–2 metadata remains readable because the Stage 3 status fields have defaults.

## 4. Refresh backend dependencies

```bash
cd ~/ragProject/backend
source .venv/bin/activate
pip install -r requirements.txt
```

Optional test dependencies:

```bash
pip install -r requirements-dev.txt
pytest -q
```

## 5. Start backend

```bash
uvicorn app.main:app --reload
```

Check `http://127.0.0.1:8000/docs`.

## 6. Refresh frontend dependencies

Make sure `node -p "process.platform"` prints `linux`, then:

```bash
cd ~/ragProject/frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## 7. First Stage 3 test

Use a normal digital PDF first.

1. Upload it in the left sidebar.
2. Verify Stage 1 and Stage 2 are valid.
3. Click **Run Stage 3**.
4. Open **Extraction viewer**.
5. Move through pages and compare overlay boxes with the source page.
6. Open **JSON** and inspect `pages[].blocks`, `lines`, `spans`, `tables`, and bounding boxes.

Then test a scanned PDF. It should explicitly warn that OCR is disabled and should not invent text.

## Stage boundary

Do not add heading/paragraph/caption classification to Stage 3. Stage 4 will consume this extraction JSON and reconstruct document structure separately.
