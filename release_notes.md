# Confy Release Notes - June 2026 Boundary Guardrail Release

Prepared for merging `av/improvements_june-2026` into `main`.

Baseline: changes since merge base `efa65b0a73af` with `origin/main`.

## Release Story

This is intentionally a small release. The branch explored shared token counters and capability descriptions, then reverted both changes to keep Confy focused on its core responsibility: configuration loading and overrides. The net result is a boundary test that prevents future ecosystem helpers from drifting back into the config library.

## Highlights

- Adds `tests/unit/test_domain_boundaries.py` to lock Confy's config-only scope.
- Documents the architectural decision that token counting belongs in LLMCore, not Confy.
- Documents the architectural decision that shared capability descriptions should stay outside Confy.
- Keeps the public runtime package unchanged after reverting the exploratory helper APIs.

## Developer Impact

Downstream packages should not depend on Confy for token estimation, model capability metadata, or agent/runtime descriptions. Confy remains the minimal configuration foundation used by the ecosystem, and this test protects that boundary explicitly.

## Operator Impact

There is no expected runtime behavior change. This release reduces future maintenance risk by making the package boundary executable in CI.

## Compatibility Notes

- No new runtime APIs remain in the package after the reverts.
- Existing Confy users should see no behavior change.
- Ecosystem packages that need token accounting should use LLMCore's token counters.

## Validation Focus

Reviewers should focus on:

- The domain-boundary test and whether it captures the intended package ownership rule.
- Confirming that no token or capability helper modules remain exported from Confy.

## By the Numbers

- 5 commits since the merge base.
- 1 file changed after the reverts.
- 62 insertions before this release-note commit.

## Representative Commits

- `4b873c1` and `9164464` - exploratory token/capability helpers.
- `1727ec5` and `18a72d2` - revert those helpers to preserve package boundaries.
- `fb5c8ef` - add the domain boundary regression test.
