You are a POMDP modeling engineer. Convert the ENVIRONMENT DESCRIPTION below into a factored
POMDP model written ONLY as one JSON object {"domain": {...}, "problem": {...}} in the MAAOS
skill-IR format. A deterministic compiler (not you) turns it into tables for a POMDP solver, and
a statistical fitter (not you) estimates every probability from data. YOUR JOB IS STRUCTURE.

FORMAT RULES
F1  domain keys: name, model_version, types, constants, parameters, observation_channels,
    predicates, skills, provenance. problem keys: name, domain, objects, init, hidden_prior,
    goal, rewards, discount.
F2  Every object you mention is a constant {"name","type"} with a declared type.
F3  Predicates are boolean: {"name","param_types","fluent"} plus "observable": false for a
    variable that is never shown. fluent=false means the value never changes.
F4  A skill has "name", "parameters" (names), "parameter_types" (parallel types),
    "preconditions" and optional "negative_preconditions" (lists of {"name","args"}), and either
    plain "effects" (one certain outcome) or "outcomes": [{"label","effects"}] with
    "outcome_label" naming the outcome a planner should hope for. An effect is
    {"predicate": {"name","args"}, "positive": true|false}. Args are parameter names or constants.
F5  "*" as an argument is allowed ONLY in a negative precondition (no grounding holds) or a
    negative effect (delete every grounding), e.g. not at(agent, *) before adding at(agent, place).
F6  Hidden (observable=false) predicates must NEVER appear in preconditions. They may appear in
    outcome cases, effects and observation cases.
F7  With two or more outcomes, give "outcome_cases": a decision list
    [{"when": [atoms], "distribution": D}], first match wins, the LAST case has "when": [].
    An atom is {"literal": {"name","args"}, "positive": bool} or {"equals": [parameter, constant]}.
F8  D is {"deterministic": label} or
    {"bernoulli": {"p": {"parameter": name}, "then": label1, "else": label2}}.
    Every probability you were not given is a NAMED PARAMETER declared in "parameters" as
    {"name": ..., "prior": {"beta": ["1", "1"]}}. Never write a number for it.
F9  "observation_channels": [{"name", "symbols"}]; the first symbol is "none". A skill's
    "observation_cases" is an object {channel: decision list}; conditions are read on the state
    AFTER the skill. Positions and other observable predicates are observed automatically.
F10 problem: "init" = observable ground literals true at the start (static ones included);
    "hidden_prior" = [{"literal": {"name","args"}, "p": {"parameter": name}}];
    "goal" = ground literals; "rewards" = {"step": r, "skills": {skill: extra}, "goal": r} as
    exact fraction strings such as "-1/50"; "discount" as a fraction string.
F11 Use exactly the skill names and parameters given in the description. Output ONLY the JSON.

EXAMPLE (a different domain)
{{EXAMPLE}}

ENVIRONMENT DESCRIPTION
{{DESCRIPTION}}
