# Request-local path binding results

Measured September 10, 2026 on the existing RTX 3070 8GB, Ryzen 9 3900X,
64GB RAM and Ollama 0.33.3. The trained Qwen2.5-Coder 1.5B adapter was unchanged.
This change targets the agent-to-specialist inspection handoff. It does not install
an automatic Codex/OpenCode integration or expand the five supported operations.

## Behavior

The caller supplies task intent plus named exact paths. The model sees short
request-local references in the existing plan shape. A per-request JSON schema
restricts the path field to registered references, and the binder resolves the
chosen reference before the ordinary executor validates and reads the target.
Unknown references cannot execute. No filenames are learned or guessed by binding.

Users and the calling agent receive the original readable request, actual path,
exit code and output/evidence. The private raw artifact records the reference map,
model prediction, planning timing and original command output for inspection.
A single substitution pass prevents braces or reference-looking text inside a
filename from becoming another binding. Output and evidence text are not rewritten.

## Paired live-model experiment

Sixty fresh synthetic tasks used random opaque filenames containing spaces,
apostrophes, brackets, Unicode and sometimes placeholder/reference-like text.
Each bound task offered two registered candidates, with the requested candidate
alternating between the first and second reference. The same actual path appeared
literally in the comparison arm. Execution results were checked against independent
PowerShell reference output; the references ran outside the timed operation.

| Measurement | Literal path generation | Bound references |
|---|---:|---:|
| Correct executed results | 60/60 | 60/60 |
| Median full operation | 481.7ms | 192.7ms |
| p95 full operation | 576.1ms | 329.3ms |
| Mean generated tokens | 46.42 | 20.40 |

Median operation latency improved 2.50x,
with 56.1% fewer generated tokens.
Both arms passed this fresh set, so this run does **not** demonstrate an accuracy
increase. The older 40-case probe's 29/40 result is a different run/dataset and must
not be substituted for this experiment's comparison arm.

The mix was 20 first-line reads, 20 last-line reads, eight literal searches,
eight JSON-field reads and four directory listings. Every operation passed in both
arms. Temperature was zero, thinking disabled, context 4096 and output limit 160.
Order alternated by case; warm-ups were recorded separately. Times include binding,
inference, validation, native fixture execution, raw-result writing, packet
construction and artifact reload. This is one sequential Windows desktop run,
not a controlled hardware microbenchmark. It excludes frontier reasoning and a
future host transport. It is not a claim of 2.5x speed across arbitrary commands.

## Execution and presentation checks

The Python suite covers all five bound operations through both native and actual
PowerShell execution, including exact Unicode/quoted paths, two-target resolution,
request-local mappings, unknown references, missing/escaping paths, deletion after
binding, readable returned plans and rejected evidence preserving raw output.

A live CLI task-file smoke test read a Unicode/apostrophe-containing log through
PowerShell and selected its error and final summary using the actual trained model.
It returned the original filename, exit code zero, source lines 2 and 3, and the
verbatim evidence. Whole CLI handoff timing reported about 702ms including planning,
PowerShell and the second model call for evidence; planning alone was about 326ms.
Those conditions differ from the native no-selection benchmark above.

## Reproduction and limitations

```powershell
python -m unittest discover -s experiments/command_model -p 'test_*.py' -v
python experiments/command_model/benchmark_bindings.py --out work/command-specialist/new-binding-trial --backend native
```

Each new output directory gets new random filenames. The original cases, hashes,
per-task packets and raw results are retained locally under
`work/command-specialist/bound-handoff-20260910/`. The live CLI fixture and raw result
are under `work/command-specialist/bound-cli-smoke/`. Historical development and
final-test data were not read, and no training occurred.

The caller must already know the exact targets. This does not solve discovery from
an ambiguous description, choosing newest files from metadata, arbitrary shell
commands, or multi-step agent planning. Correct operation/count/value selection
still requires evaluation. Original unbound requests retain the older copying
behavior. Existing access validation remains in force; a reference is not permission.
