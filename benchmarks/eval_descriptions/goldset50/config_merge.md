# config_merge

Repair `merge_config(defaults, overrides)` in `src/config_merge.py`.
Inputs are JSON-compatible, acyclic dictionaries with string keys, containing
dictionaries, lists, and JSON scalar values. Recursively merge a key only when
both its default and override values are dictionaries. Otherwise the override
replaces the default value; lists are replaced, never concatenated. Keys absent
from overrides retain their default values. Empty dictionaries merge normally.
Falsey values, including 0, False, empty strings, empty lists, and None, are real
overrides, not signals to fall back to defaults.

Repeated references to the same container within an acyclic input are in scope.
Overriding one key must not change values inherited under an unmentioned key.

Neither input may be mutated. The returned value must share no mutable nested
dictionary or list with either input, including inherited defaults and newly
introduced or replacement overrides: later mutations in either direction must
remain isolated. Preserve recursive values, ordinary scalar replacements, and
empty-input behavior. Only production Python source may be edited; visible tests
are incomplete examples of this full contract.
