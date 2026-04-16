# Changelog

## [Unreleased]

### Added
- Add configurable ultrasonic automation rules with persisted threshold, delay, cooldown, enable state, and action selection.
- Add backend-triggered automation actions for stopping the motor, homing the arm, or starting a saved workflow.
- Add a live sensor telemetry and automation management UI for creating, editing, and monitoring ultrasonic trigger rules.
- Add a persistent backend runtime state store so joint targets, execution status, sensor state, and command history survive browser refreshes and app restarts.
- Add a `motor_run` workflow step that auto-computes its stop delay from motor speed so workflows can include speed-dependent conveyor actions.

### Changed
- Redesign the control dashboard to separate live telemetry, automation rules, workflow management, and manual motion controls more clearly.
- Move UI state ownership to the backend so the browser now hydrates live robot state from persisted runtime snapshots instead of local memory.
- Extend the workflow builder UI with a motor auto-stop block for composing speed-based conveyor segments without editing JSON by hand.

### Fixed
- Fix duplicate serial-port contention from the Flask debug reloader by starting background sensor monitoring only once.
