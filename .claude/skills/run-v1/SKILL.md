---
name: run-v1
description: Run the supported Symbolic-Twin BoxPush V1 runner in default, symbolic-primary, live-local-LM, or help mode.
argument-hint: default|symbolic|headless|live|help
disable-model-invocation: true
---

# Run Supported BoxPush V1

Mode: `$ARGUMENTS`

Run from:

```bash
cd functional_layer/custom_env/box_push/env
```

Supported commands documented by the current repository:

### default

```bash
python box_push_v1_run.py
```

### symbolic

```bash
python box_push_v1_run.py --policy symbolic_primary
```

### live

Only when the user explicitly invokes `/run-v1 live`:

```bash
python box_push_v1_run.py --nl live
```

This uses the configured local DSPy/Ollama path and is not part of the default
offline acceptance gate.

### help

```bash
python box_push_v1_run.py --help
```

Do not run the pre-V1 `box_push_centralized.py` as the supported V1 runner.

### headless

The runner already implements `--headless` (no pygame window). Use it for
non-GUI verification and baseline capture:

```bash
SDL_VIDEODRIVER=dummy python box_push_v1_run.py --headless
SDL_VIDEODRIVER=dummy python box_push_v1_run.py --headless --policy symbolic_primary
```

Do not invent other flags; check `--help` first.
