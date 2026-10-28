# Design notes

How calculo-diario works inside, and why it is built this way. The code and the exercise files are in Spanish (it was built for a Spanish engineering course); this document is the English map.

## 1. The idea

You solve on paper. The program decides what is due today, checks the result objectively and records everything. Data is plain text inside the repository.

| Piece | What it does | Where |
|---|---|---|
| Exercise cards (`fichas`) | Each card is a *family* of exercises with parameters, e.g. `∫ x·e^(a·x^2) dx` with a ∈ {1, 2, 3, −1}. Every review generates a fresh variant from a recorded seed | `programa/fichas/*.toml` |
| Engine | Builds today's queue, generates the variant, reads and checks the answer, schedules reviews, computes statistics | `programa/calculo/` |
| Log | One JSON line per attempt; append-only; the single source of truth | `usuario/datos/registro.jsonl` |
| Interfaces | Window (pywebview + KaTeX), terminal, and a JSON command mode for scripts or a human reviewer | `practica.py`, `calculo/ventana.py`, `interfaz/` |

## 2. A session

1. **Queue.** 5 exercises (2 on a "minimum day"): 1 algebra warm-up, then partial derivatives/ODEs, derivatives and integrals. Overdue reviews always get a seat; backlog after missed days is spread over several days, most urgent first. The session starts with the exercise most likely to go well.
2. **Confidence.** Before answering, the student rates confidence 1–5 (used for calibration, never for the grade).
3. **Answer.** Only the final result, in the notation used in class: `e^2x/2 + C`, `sen x cos x`, `ln|x-3|`, `2±3i`, `y = C1 e^x + C2 e^(3x)`. The window shows a neutral "I read: …" preview rendered with KaTeX before checking.
4. **Help.** Three graded hints (shape → technique → first step), then the worked solution. "I don't know where to start" shows the worked example of the technique and counts as hint 2.
5. **Close.** A short feeling score and an optional comment; the day's block is written to the diary and the data is committed.

## 3. Checking answers

- **Integrals:** the answer is differentiated and compared with the integrand, symbolically and at 20 random points. Any valid antiderivative is accepted (they may differ by a constant). A missing `+C` or a missing absolute value is a warning, not a failure.
- **Derivatives, partial derivatives, definite integrals:** compared with the key by random-point sampling (no `simplify`, which could take minutes with roots and logs; a check takes < 0.1 s).
- **ODE solutions:** substituted into the equation. General solutions must contain two independent constants.
- **Algebra:** values checked against an identity, matched by label when labels are given (`h = 3, k = 4`).
- **Every key is verified with SymPy** when the card is generated and in the test suite.
- **Reader:** `calculo/expresiones.py` accepts the notation people actually type: implicit products (`2x`, `x sen x`), `sen/tg/arctg`, `e^2x`, `√`, decimal comma, `C` anywhere, labels in any order. A preview reader runs in a separate process with a 2 s hard timeout, so `9**9**9**9` cannot freeze the window.
- **Diagnosis:** when an answer is wrong, rules detect the typical mistake: factor too many/few, sign, forgotten chain or product rule, wrong variable, differentiating instead of integrating, swapped limits, roots with the wrong sign, ODE residual. Cards can also carry their own typical errors.

## 4. Scheduling

### 4.1 Objective grade

| Fact | FSRS grade |
|---|---|
| Wrong, or hint 4 (full solution) | 1 Again |
| Right with hint 2–3, or after a failed attempt | 2 Hard |
| Right first time without help (or hint 1) | 3 Good |
| Right without help, faster than the student's own median for that technique, confidence ≥ 4 | 4 Easy |

Failed checks are counted: otherwise guessing until right would score as knowing it.

### 4.2 FSRS

The scheduler is **FSRS** (`fsrs` 6.x), with target retention 0.90 and a 60-day cap (0.85 gave 4 → 31 day intervals after two successes, too much for freshly learned procedures; 0.90 gives 2 → 11 → 46). FSRS state is **never stored**: it is rebuilt from the log on every run, so there is no corrupt state to repair. Days are counted at local noon, so the time of practice does not change intervals. `informe` reports calibration (predicted vs. observed recall) and asks for a retention adjustment only after 400 reviews.

### 4.3 Mastery per technique

Each technique (substitution, parts, partial fractions...) has a success rate p with a Beta(1,1) prior over the **last 8 attempts** (a success with hints counts half). A technique is mastered when P(p > 0.7) ≥ 0.5, with at least 4 attempts and successes on 2 different cards. A step of the ladder opens when half of the previous step is mastered; progress is a milestone stored in `usuario/datos/progreso.jsonl` and never goes back. A card that fails 4 times in a row is parked for 7 days and the related algebra card is suggested.

### 4.4 Implicit repetition

`fichas/grafo.toml` is a DAG of techniques ("integration by parts contains the power rule and linear substitution"), validated on load; every edge has a written justification. When a real attempt scores ≥ 3, the overdue card with the lowest retrievability of each contained technique gets a virtual "Good" review at that date. It is deterministic, never creates cards, never touches the log and only postpones what was already due.

### 4.5 Exams, placement test, mock exams

- `fichas/calendario.toml` opens an exam's techniques some days before it, even if the ladder has not reached them. `examen` runs an extra session with only those techniques (weakest first, interleaved).
- The placement test is adaptive and derived from the log: per group it climbs the ladder while the student answers without hints and stops at the first failure.
- `simulacro` is a timed mock exam: no hints and no feedback until the end; the time limit is checked in Python.

### 4.6 Worked examples with gaps (fading)

The first time a technique appears, a fully worked example is shown. After 1 success, one step is hidden ("Step 3: ____"), after 2 successes two steps, and from 3 successes no example. After a failure, the full example comes back.

## 5. Data safety

The data files (`usuario/datos/*.jsonl`) only grow, one line per fact. "Losing data" means a line that was in the last backup is missing; "recovering" is the union of lines, never a deletion.

| Risk | Mechanism |
|---|---|
| Crash mid-write | File lock with PID (stale locks from dead processes are broken at once), `fsync`, line re-read; on failure the partial write is truncated and retried once, then a clear error |
| Damaged line | Moved aside to `apartado-YYYY-MM-DD.jsonl` on start-up (written there first, then the original is rewritten atomically) |
| File overwritten or truncated | On start-up the data is compared with the last backup; missing lines are reported and can be merged back |
| Disk failure | Verified backup (SHA-256 manifest) on start and on close, only if something changed, outside the repo; 30 daily + one per month |
| Lost laptop | `cerrar` commits and pushes; `doctor` warns about unpushed commits older than 2 days |
| Two computers | `merge=union` in `.gitattributes`, `pull --rebase --autostash`, a rebase that conflicts is aborted and reported, never left half-done |

## 6. Interfaces

- **Service layer** (`calculo/servicio.py`, class `Sesion`): the session logic without `input()` or `print`. Everything that matters lives on disk (log and `.cache` under lock), so the window, the terminal and the JSON commands can pick up the same session. Every public method returns a JSON-serialisable dict with `ok`; exceptions become `{ok: False, error}` and go to a log.
- **Window** (`calculo/ventana.py` + `interfaz/`): pywebview with the system WebView2, KaTeX 0.19.1 bundled locally (no network, strict CSP, `trust: false`, text via `textContent`, never `innerHTML`). A custom converter turns class notation into LaTeX *as written* (SymPy's printer reorders `3(x-2)` into `3x - 6`, which would give away the answer). Single instance, launched with `pythonw` so no console stays open; if the window cannot open, exit code 3 and the terminal takes over.
- **Terminal** (`practica.py hoy`): the same session, keyboard only.
- **JSON / reviewer mode**: `cola`, `comprobar`, `pista`, `registrar`, `pendientes`, `resolver` let a script or a person run a session step by step. Students can flag "my answer was right" (a claim): it is graded 2 provisionally and listed in `pendientes` until someone resolves it.

## 7. Limits

- It checks the result, not the steps.
- It does not read handwriting.
- FSRS defaults come from flash-card data, not procedures; calibration is reported honestly and only acted on with enough data (≥ 400 reviews).
