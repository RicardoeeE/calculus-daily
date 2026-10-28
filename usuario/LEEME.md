# usuario/

**EN** — Your personal practice data lives here and is created on first use. `cerrar` commits it to *your* clone, so keep that clone private if you push it anywhere. This public repository ships it empty.

**ES** — Aquí van tus datos de práctica; se crean solos la primera vez. `cerrar` los guarda con git en *tu* copia: si la subes a GitHub, que sea privada. Este repositorio público los trae vacíos.

| Path | What it is |
|---|---|
| `datos/registro.jsonl` | One line per attempt (append-only). Source of truth for FSRS |
| `datos/notas.jsonl` | Feelings, complaints and "my answer was right" claims |
| `datos/progreso.jsonl` | Highest ladder step reached per group |
| `diario.md` | Human-readable diary, one block per day |
| `revisiones/` | Weekly review, generated automatically |
| `simulacros/` | Mock-exam reports |

Do not edit `datos/` by hand: the program only appends, verifies each line and keeps SHA-256-checked backups. `programa\practica.py datos` shows their status. A fictitious sample of the log format is in `programa/docs/ejemplo-registro.jsonl`.
