# Apply Stage 4.4 to the existing project

Back up first:

```bash
cd ~
cp -a ragProject ragProject_before_stage4_4
```

Copy the patch contents into the matching paths under `~/ragProject/`.

Changed files:

```text
backend/app/schemas.py
backend/app/services/canonical.py
backend/tests/test_stage4_canonical.py
frontend/src/App.tsx
frontend/src/types.ts
frontend/src/styles.css
```

Then test:

```bash
cd ~/ragProject/backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Expected:

```text
18 passed
```

Restart the backend and frontend. Existing Stage 1–3 artifacts can remain. Re-run **Stage 4 only** for each document that you want regenerated with canonical schema `1.3`.
