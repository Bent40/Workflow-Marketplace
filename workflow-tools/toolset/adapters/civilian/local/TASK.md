<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# TASK — microtask packet contract (profile: civilian)

Fill one packet per microtask. Do only what the packet specifies, then stop and hand back.

## Packet
- objective: <one concrete outcome>
- allowed_files: <explicit minimal set you may read/edit>
- forbidden_files: <files you must not touch>
- context_budget: <ceiling for this packet>
- max_edit_size: <cap, e.g. one function / <= N changed lines>
- expected_output_format: <usually a patch/diff, not prose>
- validation: <exact command to run, or manual check>
- stop_condition: <stop after the one objective>
- handoff_summary_format: <shape of the terse summary for the orchestrator>

## Execution rules
- Non-mockable blocker → stop and ask; never guess, especially on security.  <!-- rule:blockers.non_mockable_escalate severity:high -->
- Each microtask lists allowed files and forbidden files explicitly.  <!-- rule:local.allowed_and_forbidden_files_required severity:high -->
- One objective per microtask; orchestrator owns decomposition and integration.  <!-- rule:local.decompose_into_microtasks severity:high -->
- One objective per microtask — nothing bundled.  <!-- rule:local.one_objective_per_task severity:high -->
- Orchestrator owns decomposition, integration, and final acceptance — not the local model.  <!-- rule:local.orchestrator_owns_integration severity:high -->
- Mockable blocker → stub it visibly, keep going, track the follow-up.  <!-- rule:blockers.mockable_continue_tracked severity:medium -->
- Stop after one microtask — hand back, don't chain into the next.  <!-- rule:local.stop_after_microtask severity:medium -->
