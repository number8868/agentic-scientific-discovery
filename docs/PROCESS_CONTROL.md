# B trusted process control

`nova.process_control.ProcessController` is the minimal host-side boundary for
running a registered scientific callable.  The host gives it an explicit
name-to-function registry and invokes a name with a positive wall-clock
deadline.  The child is created with Python's `spawn` context and is always
joined before the call returns or raises.

The parent drains the result pipe in a supervised reader thread while the
worker is running. Waiting for exit before reading can deadlock when a result
exceeds the pipe buffer. One deadline covers execution, result receipt and
worker exit after synchronous `Process.start()` returns; synchronous creation
and termination/reaping cleanup are outside that budget.

Only registered, importable top-level functions are accepted.  There is no
shell command, module name, path, or source-code execution API.  Unknown names,
lambda functions, and invalid deadlines are rejected before a worker is
started.

When the deadline expires, the host terminates the worker, joins it, and uses
`kill` as a final escalation where supported.  `WorkerTimeoutError` is
distinct from `WorkerExecutionError` (a callable's failure) and
`ProcessControlError` (a malformed or unexpectedly silent worker).  The
current MVP does not implement persistent leases or restart/recovery; callers
must record the timeout as a terminal attempt and decide whether a new attempt
is authorized.

Example:

```python
from nova.process_control import ProcessController

controller = ProcessController({"registered_experiment": registered_experiment})
result = controller.run("registered_experiment", (spec,), deadline_seconds=120)
```

The worker boundary is a host control, not proof of scientific validity or
authorization.  Registry ownership, contract validation, artifact persistence,
and event logging remain responsibilities of the surrounding B workflow.
