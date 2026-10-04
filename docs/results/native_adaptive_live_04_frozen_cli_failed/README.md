# Native run 04: frozen protocol, CLI acceptance failed

Executed on main c6cea09 with configurable gpt-6-luna and a shared 600-second deadline. The primary family screen was host-seeded, not autonomously chosen.

Actual Planner, Skeptic, PI and Runner discovery stages completed. Final Skeptic reviewed the follow-up and PI froze protocol NOVA-FINAL-d1009139bc9744ba. Holdout NOVA-HOLDOUT-6b83a417827443f6 is registered but unexecuted. An overlong freeze explanation was rejected; a shortened retry succeeded before the protocol was frozen.

Original CLI exit code: **1**. The host rejected the final CLI transcript because it did not match the guarded freeze-turn response hash. The captured output contains intermediate PI replies as well as the final reply. This bundle is not a clean end-to-end success and no original failure event has been rewritten.

Final-stage PI text was printed but not persisted into its response table before validation failed. The original terminal capture is retained privately under runs/native-adaptive-live-04/original-terminal.json. Portable scientific artifacts pass the read-only discovery audit; that audit is not native workflow acceptance. No holdout results or speedup claim are established.

Posthoc investigation: the 396-character final-session reply extracted from the captured terminal output exactly matches the recorded final PI turn metadata hash, and passes the existing three-tool verifier against the original audit. The recorded failure cannot currently be reproduced with that extracted input. This does not establish what exact input reached the failing verifier, explain the original mismatch, or change the original exit code. No permissive runtime matching change is justified. The launcher fix preserves the exact verifier input before validation on future runs, enabling direct diagnosis rather than inference from combined stdout.
